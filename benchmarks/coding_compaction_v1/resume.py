"""Behavioral resume evaluation: checkpoint → next-action oracle, not recall.

The default comparison is ``dsh_native`` against ``wsc_gater``, the current
default WSC variant. Pass ``--arms`` to evaluate older or experimental arms.

Each scenario ends with a state whose correct next action is fixed by an oracle
(required/forbidden). The arms' checkpoints are handed to a fresh model,
which may fetch one index key; the emitted JSON actions are scored mechanically.
Compaction work itself is unchanged and still measured by live.py.

    python benchmarks/coding_compaction_v1/resume.py --jobs 2
    python benchmarks/coding_compaction_v1/resume.py --self-check
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'benchmarks')]

from coding_compaction_v1 import live  # noqa: E402
from coding_compaction_v1 import longhorizon  # noqa: E402
from coding_compaction_v1 import resume_cases  # noqa: E402
from coding_compaction_v1 import cost as cost_module  # noqa: E402
from wsc.distillation_gate import (DECISION, FAILURE, high_signal, instruction,  # noqa: E402
                                   needs_distillation, should_distil)
from wsc.resume_contract import resume_contract  # noqa: E402

RESUME_PROMPT = '\n'.join([
    'You are resuming a coding session. The state above is all you have.',
    'Return only JSON of this form:',
    '{"actions":[{"tool":"edit","file":"<path>","content":"<replacement text>"},'
    '{"tool":"run","command":"<command>"},{"tool":"read","file":"<path>"},'
    '{"tool":"fetch","key":"E<number>"}]}',
    'Rules:',
    '- Emit only the actions needed to continue now, in order; no prose, no fences.',
    '- File changes must use edit with the exact text to write; never modify files through a shell command.',
    '- If a fact must be recalled exactly but is not in the state, fetch its index key or read the file; '
    'the engine returns what you asked for and then expects your final actions. Do not guess such a value.',
])


# Default WSC variant after the threshold runs: threshold-triggered extraction
# + engine value ledger + resume contract v2, without the high-signal hint
# (``wsc_nosig``). ``wsc_gater`` is kept as the hint-on ablation.
DEFAULT_ARMS = ('dsh_native', 'wsc_nosig')
RESUME_V2_ARMS = {'wsc_gater', 'wsc_both', 'wsc_nosig', 'wsc_next'}
# Same checkpoint as wsc_nosig (same distill labels reuse the response cache),
# only the resume text differs: isolates what the contract wording costs.
RESUME_V1_ARMS = {'wsc_nosig_v1'}


def resume_prompt(arm, checkpoint=''):
    if arm in RESUME_V2_ARMS:
        return resume_contract('Observed values' in (checkpoint or ''))
    return RESUME_PROMPT


def normalized(text):
    return ' '.join(str(text or '').lower().split())


def action_match(rule, action):
    if not isinstance(action, dict) or action.get('tool') != rule.get('tool'):
        return False
    if rule['tool'] == 'run':
        return normalized(rule['command']) in normalized(action.get('command'))
    if rule['tool'] == 'edit':
        if normalized(rule.get('file')) != normalized(action.get('file')):
            return False
        content = normalized(action.get('content'))
        if normalized(rule.get('content')) not in content:
            return False
        if rule.get('unless') and normalized(rule['unless']) in content:
            return False
        return True
    if rule['tool'] == 'fetch':
        return normalized(rule.get('key')) == normalized(action.get('key'))
    return False


def actions_of(parsed):
    if not isinstance(parsed, dict) or not isinstance(parsed.get('actions'), list):
        return []
    return [action for action in parsed['actions'] if isinstance(action, dict)]


def score(parsed, required, forbidden):
    actions = actions_of(parsed)
    matched = [rule for rule in required if any(action_match(rule, action) for action in actions)]
    violations = [rule for rule in forbidden if any(action_match(rule, action) for action in actions)]
    targets = {normalized(rule.get('file')) for rule in required if rule.get('tool') == 'edit'}
    extra = [action for action in actions
             if not any(action_match(rule, action) for rule in required)
             and not (action.get('tool') == 'read' and normalized(action.get('file')) in targets)]
    return {'success': len(matched) == len(required) and not violations,
            'required_hit': len(matched), 'required_total': len(required),
            'violations': len(violations), 'extra': len(extra),
            'actions': actions, 'fetches': [str(action.get('key')) for action in actions
                                            if action.get('tool') == 'fetch'],
            'reads': [str(action.get('file')) for action in actions
                      if action.get('tool') == 'read']}


def required_literals(case):
    out = []
    for rule in case.get('required') or []:
        out += [rule.get('file'), rule.get('content') or rule.get('command')]
    return [str(value) for value in out if value]


def attribution(case, checkpoint, sources):
    """Where a failed arm could have learned the required values.

    ``checkpoint`` means the value is stated in the state; ``fetchable`` means
    an index key in the state points at a source that contains it. Neither means
    the engine never made the value available, which is a WSC-side gap.
    """
    literals = required_literals(case)
    text = normalized(checkpoint)
    index_keys = re.findall(r'\[(E\d+)\]', checkpoint)
    pool = normalized(' '.join(str(sources.get(key) or '') for key in index_keys))
    stated = [value for value in literals if normalized(value) in text]
    fetchable = [value for value in literals
                 if value not in stated and normalized(value) in pool]
    return {'literals': literals, 'stated': stated, 'fetchable': fetchable,
            'classification': ('model' if len(stated) == len(literals) and literals
                               else 'recovery' if stated or fetchable else 'wsc')}


def resolve_evidence(actions, sources, files):
    """Return the text the engine would hand back for this turn's fetch/read."""
    lines = []
    for action in actions:
        if action.get('tool') == 'fetch':
            key = str(action.get('key'))
            lines.append('Fetched ' + key + ':\n' + (sources.get(key) or 'no such key'))
        elif action.get('tool') == 'read':
            name = str(action.get('file'))
            lines.append('Read ' + name + ':\n' + (files.get(name) or 'file not available'))
    return '\n\n'.join(lines), [str(action.get('key')) for action in actions
                                if action.get('tool') == 'fetch']


def resume_call(model, checkpoint, sources, files, secret, label, prompt=RESUME_PROMPT,
                turns=3):
    context = ''
    parsed = {}
    fetches, fetch_hit = [], None
    for turn in range(turns):
        final = turn == turns - 1
        tail = ('\n\nNo more evidence can be returned. Return only your final actions now; '
                'do not fetch or read.') if final else ''
        body = checkpoint + ('\n\n' + context if context else '') + '\n\n' + prompt + tail
        output = model.chat([{'role': 'user', 'content': body}], max_tokens=16384,
                            label=label + ('' if turn == 0 else f'-turn{turn}'))
        parsed = live.json_object(output['text']) or {}
        if live.json_object(output['text']) is None:
            parsed = live.json_object(model.chat([
                {'role': 'user', 'content': body},
                {'role': 'assistant', 'content': output['text']},
                {'role': 'user', 'content': 'Return only the JSON object.'},
            ], max_tokens=16384, label=label + f'-retry{turn}')['text']) or {}
        pending = [action for action in actions_of(parsed)
                   if action.get('tool') in ('fetch', 'read')]
        if not pending or final:
            break
        evidence, keys = resolve_evidence(pending, sources, files)
        fetches += keys
        for text in evidence.split('\n\n'):
            if secret and secret in text:
                fetch_hit = True
        context = (context + '\n\n' + evidence).strip()
        if secret is None:
            fetch_hit = False
    return parsed, bool(fetches), fetch_hit


def signal_hint(pending: list) -> str:
    """What a compaction should not summarize away: failures and recorded decisions."""
    lines = []
    for item in pending:
        if item.get('type') == 'message' and item.get('role') == 'assistant':
            text = ' '.join((live.item_text(item) or '').split())
            if DECISION.search(text):
                lines.append(text[:180])
        elif item.get('type') == 'function_call_output':
            text = ' '.join(str(item.get('output') or '').split())
            if FAILURE.search(text):
                lines.append(text[:180])
    if not lines:
        return ''
    return ('High-signal lines in this region (keep the decision they record):\n'
            + '\n'.join(f'- {line}' for line in lines[:4]))


def wsc_chain(model, case, rounds, budget, *, lean=False, rel=False, gate=False,
              ext=False, ext2=False, tank=False, signals=True, threshold_chars=None,
              family=None, next_banner=False, norevise=False):
    """WSC semantics over N rounds: the model rewrites the whole ledger each round.

    ``lean`` keeps the same engine and sends only the new round plus the current
    ledger after the first round, using the merged create/update prompt.
    ``ext`` swaps in the extraction-only contract; ``ext2`` drops value copying
    because the engine already lists exact values. ``gate`` calls the model only
    on rounds carrying a user instruction or a high-signal failure/decision.
    ``signals`` controls only the high-signal hint attached at threshold
    compaction; it does not change which rounds are distilled. ``tank`` hides
    ledger facts that only restate an engine value from the presentation.
    ``next_banner`` gives a recorded next action its own line. ``norevise`` is
    a diagnostic only: it extracts relations but never applies a revision.
    """
    adapter = live.CodexCheckpointAdapter()
    tag = case['case']
    family = family or ('gate' if (gate and ext) else 'eco' if gate else
                        'ext' if ext else 'lrel' if (lean and rel) else
                        'rel' if rel else 'lean' if lean else 'wsc')
    items_all, ids_all, events_all, control, entries = [], [], [], [], []
    last_signal = 0
    pending, pending_ids, pending_chars = [], [], 0
    for number, delta in enumerate(rounds, 1):
        base = len(items_all)
        events = adapter.import_items(delta, thread_id=tag, start_ordinal=base,
                                      observed_at=live.observed_at(base, len(delta)))
        ids_delta = [event.id for event in events]
        items_all += delta
        events_all += events
        ids_all += ids_delta
        control += [event.text for event in events if event.kind == 'message'
                    and event.role == 'user' and (event.text or '').strip()]
        rows = [{'ref': f"{entry['id']}@{entry['rev']}", 'kind': entry['kind'],
                 'text': entry['text']} for entry in entries if entry['status'] == 'active']
        if threshold_chars:
            pending += delta
            pending_ids += ids_delta
            pending_chars += len(json.dumps(delta))
            if number < len(rounds) and pending_chars < threshold_chars:
                live.thin_expire(entries, events_all, base=base if number > 1 else 0)
                continue
            body, source_ids = pending, pending_ids
            hint = signal_hint(pending) if signals else ''
            pending, pending_ids, pending_chars = [], [], 0
        else:
            if gate and number > 1:
                if not should_distil(delta, round_number=number, last_signal=last_signal):
                    live.thin_expire(entries, events_all, base=base if number > 1 else 0)
                    continue
                if high_signal(delta) and not instruction(delta):
                    last_signal = number
            body = delta if (lean or gate or ext or ext2) else items_all
            source_ids = ids_delta if lean else ids_all
            hint = ''
        call = (live.distil_ext2 if ext2 else live.distil_ext if ext
                else live.distil_rel if (rel or gate)
                else live.distil_lean if lean else live.distil)
        kwargs = {'hint': hint} if (ext or ext2) else {}
        if norevise:
            kwargs['contract'] = live.EXT_NOREV
        raw = call(model, body, rows, number, f'{tag}:{family}-distill-r{number}',
                   **kwargs)['value']
        seq = len(items_all) - 1
        for position, item in enumerate((raw.get('entries') or [])[:8]):
            text = ' '.join(str(item.get('text') or '').split())
            if not text:
                continue
            cites = [n for n in (item.get('cites') or [])
                     if isinstance(n, int) and 1 <= n <= len(body)]
            entries.append({'id': f'w{number}-{position + 1}', 'rev': 1,
                            'kind': str(item.get('kind') or 'fact'), 'text': text[:220],
                            'sources': tuple(source_ids[n - 1] for n in dict.fromkeys(cites)),
                            'seq': seq, 'status': 'active',
                            'invalid_when': item.get('invalid_when')
                            if isinstance(item.get('invalid_when'), dict) else None})
        if not norevise:
            by_id = {entry['id']: entry for entry in entries if entry['status'] == 'active'}
            for item in (raw.get('revise') or [])[:8]:
                match = re.match(r'(.+)@(\d+)$', str(item.get('ref', '')))
                text = ' '.join(str(item.get('text') or '').split())
                if not match or not text or match.group(1) not in by_id:
                    continue
                old = by_id[match.group(1)]
                old['status'] = 'superseded'
                entries.append({**old, 'rev': old['rev'] + 1, 'text': text[:220],
                                'seq': seq, 'status': 'active'})
                by_id[old['id']] = entries[-1]
            for ref in (raw.get('supersede') or [])[:8]:
                match = re.match(r'(.+)@(\d+)$', str(ref))
                if match and match.group(1) in by_id:
                    by_id[match.group(1)]['status'] = 'invalidated'
        live.thin_expire(entries, events_all, base=base if number > 1 else 0)
    values = live.value_rows_from_events(events_all)
    index = [row for row in live.index_from_events(events_all) if row['kind'] != 'value']
    receipts = live.receipts_from_events(events_all)
    state = live.engine_state(entries, events_all, receipts)
    shown = live.merge_engine_values(entries, values) if tank else entries
    text = live.passage_text(control, shown, state, live.recent_receipts(receipts),
                             index, budget, values=values,
                             dropped=live.archived_without_slot(events_all, index + values),
                             next_banner=next_banner)
    return {'presented': text, 'sources': {row['key']: row.get('text', '')
                                           for row in list(index) + list(values)}}


def checkpoints(model, case, root, arms=None):
    wanted = set(arms or DEFAULT_ARMS)
    rounds = case.get('rounds') or [case['items'], case['round2']['items']]
    region = '\n'.join(live.arms.flatten(item) for item in rounds[0])
    override = case.get('budget')
    budget = override or max(4096, int(len(region.encode()) * live.DEFAULT_BUDGET_FRACTION))
    out = {}

    if 'dsh_native' in wanted:
        presented = None
        threshold = case.get('threshold_chars')
        if threshold:
            pending, chars = [], 0
            for number, delta in enumerate(rounds, 1):
                pending += delta
                chars += len(json.dumps(delta))
                if number < len(rounds) and chars < threshold:
                    continue
                result = live.run_native(model, pending, presented, budget,
                                         label=f'{case["case"]}:native-r{number}')
                presented = result['presented']
                pending, chars = [], 0
        else:
            for number, delta in enumerate(rounds, 1):
                result = live.run_native(model, delta, presented, budget,
                                         label=f'{case["case"]}:native-r{number}')
                presented = result['presented']
        out['dsh_native'] = {'presented': presented, 'sources': {}}

    wsc_budget = override or longhorizon.BUDGET
    threshold = case.get('threshold_chars')
    if 'wsc' in wanted:
        out['wsc'] = wsc_chain(model, case, rounds, wsc_budget)
    if 'wsc_lean' in wanted:
        out['wsc_lean'] = wsc_chain(model, case, rounds, wsc_budget, lean=True)
    if 'wsc_rel' in wanted:
        out['wsc_rel'] = wsc_chain(model, case, rounds, wsc_budget, rel=True)
    if 'wsc_lrel' in wanted:
        out['wsc_lrel'] = wsc_chain(model, case, rounds, wsc_budget, lean=True, rel=True)
    if 'wsc_eco' in wanted:
        out['wsc_eco'] = wsc_chain(model, case, rounds, wsc_budget, lean=True, rel=True,
                                   gate=True)
    if 'wsc_ext' in wanted:
        out['wsc_ext'] = wsc_chain(model, case, rounds, wsc_budget, lean=True, ext=True)
    if 'wsc_gate' in wanted:
        out['wsc_gate'] = wsc_chain(model, case, rounds, wsc_budget, lean=True, ext=True,
                                    gate=True)
    if 'wsc_tank' in wanted:
        out['wsc_tank'] = wsc_chain(model, case, rounds, wsc_budget, lean=True, ext=True,
                                    gate=True, tank=True, family='tank')
    # EXT2 ablation: identical trigger policy to wsc_nosig, only the extraction
    # contract differs (engine already lists exact values).
    if 'wsc_gatex' in wanted:
        out['wsc_gatex'] = wsc_chain(model, case, rounds, wsc_budget, lean=True, ext2=True,
                                     gate=True, signals=False, threshold_chars=threshold,
                                     family='gatex')
    if 'wsc_gater' in wanted:
        out['wsc_gater'] = wsc_chain(model, case, rounds, wsc_budget, lean=True, ext=True,
                                     gate=True, threshold_chars=threshold, family='gater')
    if 'wsc_nosig' in wanted:
        out['wsc_nosig'] = wsc_chain(model, case, rounds, wsc_budget, lean=True, ext=True,
                                     gate=True, signals=False, threshold_chars=threshold,
                                     family='nosig')
    if 'wsc_nosig_v1' in wanted:
        # Identical chain and labels: the distill calls hit the cache of the
        # wsc_nosig arm in the same model instance, so only the resume differs.
        out['wsc_nosig_v1'] = wsc_chain(model, case, rounds, wsc_budget, lean=True, ext=True,
                                        gate=True, signals=False, threshold_chars=threshold,
                                        family='nosig')
    if 'wsc_nored' in wanted:
        # Diagnostic only: extraction without revision judgment. A later round
        # that contradicts an earlier relation is left unresolved.
        out['wsc_nored'] = wsc_chain(model, case, rounds, wsc_budget, lean=True, ext=True,
                                     gate=True, signals=False, threshold_chars=threshold,
                                     norevise=True, family='nored')
    if 'wsc_next' in wanted:
        # Same compression calls as wsc_nosig (cache reuse); only the checkpoint
        # presentation gives a recorded next action its own line.
        out['wsc_next'] = wsc_chain(model, case, rounds, wsc_budget, lean=True, ext=True,
                                    gate=True, signals=False, threshold_chars=threshold,
                                    next_banner=True, family='nosig')
    if 'wsc_both' in wanted:
        out['wsc_both'] = wsc_chain(model, case, rounds, wsc_budget, lean=True, ext2=True,
                                    gate=True, tank=True, family='both')

    if 'wsc_thin' in wanted:
        thin = longhorizon.run_thin_chain(model, case, rounds, wsc_budget)
        out['wsc_thin'] = {'presented': thin[-1]['presented'],
                           'sources': {row['key']: row.get('text', '')
                                       for row in thin[-1]['index']}}
    return out


def usage_by_arm(model, case_name):
    """Compression and resume token spend per arm, keyed by call label."""
    result = {arm: {'compression': cost_module.empty(), 'resume': cost_module.empty()}
              for arm in ('dsh_native', 'wsc', 'wsc_lean', 'wsc_rel', 'wsc_lrel',
                          'wsc_eco', 'wsc_ext', 'wsc_gate', 'wsc_tank', 'wsc_gatex',
                          'wsc_gater', 'wsc_both', 'wsc_nosig', 'wsc_nosig_v1',
                          'wsc_nored', 'wsc_next', 'wsc_thin')}
    for call in model.calls:
        label = call['label']
        if not label.startswith(case_name + ':'):
            continue
        usage = call.get('usage') or {}
        if ':resume-' in label:
            arm = re.sub(r'-(?:turn|retry)\d+$', '', label.split(':resume-', 1)[1])
            bucket = 'resume'
        elif ':native-' in label:
            arm, bucket = 'dsh_native', 'compression'
        elif ':nosig-' in label:
            arm, bucket = 'wsc_nosig', 'compression'
        elif ':nored-' in label:
            arm, bucket = 'wsc_nored', 'compression'
        elif ':tank-' in label:
            arm, bucket = 'wsc_tank', 'compression'
        elif ':gatex-' in label:
            arm, bucket = 'wsc_gatex', 'compression'
        elif ':gater-' in label:
            arm, bucket = 'wsc_gater', 'compression'
        elif ':both-' in label:
            arm, bucket = 'wsc_both', 'compression'
        elif ':gate-' in label:
            arm, bucket = 'wsc_gate', 'compression'
        elif ':ext-' in label:
            arm, bucket = 'wsc_ext', 'compression'
        elif ':eco-' in label:
            arm, bucket = 'wsc_eco', 'compression'
        elif ':lrel-' in label:
            arm, bucket = 'wsc_lrel', 'compression'
        elif ':rel-' in label:
            arm, bucket = 'wsc_rel', 'compression'
        elif ':lean-' in label:
            arm, bucket = 'wsc_lean', 'compression'
        elif ':lh-thin-' in label:
            arm, bucket = 'wsc_thin', 'compression'
        elif ':wsc-distill-' in label:
            arm, bucket = 'wsc', 'compression'
        else:
            continue
        row = result.get(arm, {}).get(bucket)
        if row is None:
            continue
        row['calls'] += 1
        cost_module.add(row, usage)
    return result


def measure(model, case, out, arms=None, subdir=''):
    directory = out / case['case'] / subdir if subdir else out / case['case']
    directory.mkdir(parents=True, exist_ok=True)
    states = checkpoints(model, case, directory, arms=arms)
    report = {'case': case['case'], 'arms': {}}
    for arm, state in states.items():
        prompt = resume_prompt(arm, state['presented'])
        parsed, fetched, fetch_hit = resume_call(
            model, state['presented'], state['sources'], case.get('files') or {},
            case.get('secret'), f'{case["case"]}:resume-{arm}', prompt=prompt)
        result = score(parsed, case['required'], case['forbidden'])
        if fetched and not case.get('secret'):
            result['extra'] += 1
        secret = case.get('secret')
        grounded = None if secret is None else bool(fetch_hit or secret in state['presented'])
        if grounded is False:
            result['success'] = False
        result.update({'bytes': len(state['presented'].encode()),
                       'fetched': fetched, 'fetch_hit': fetch_hit,
                       'grounded': grounded, 'raw': parsed,
                       'attribution': attribution(case, state['presented'], state['sources'])})
        report['arms'][arm] = result
        (directory / f'checkpoint-{arm}.txt').write_text(state['presented'], encoding='utf-8')
        (directory / f'resume-{arm}.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    usage = usage_by_arm(model, case['case'])
    for arm, row in report['arms'].items():
        row['usage'] = usage[arm]
    report['usage'] = usage
    calls = [{'label': call['label'], 'usage': call.get('usage') or {},
              'finish': call.get('finish')}
             for call in model.calls if (call.get('label') or '').startswith(case['case'] + ':')]
    (directory / 'calls.jsonl').write_text(
        '\n'.join(json.dumps(row, ensure_ascii=False) for row in calls), encoding='utf-8')
    return report


def _spread(values):
    import statistics
    values = [float(value) for value in values]
    return {'mean': round(sum(values) / len(values), 6),
            'sd': round(statistics.pstdev(values), 6) if len(values) > 1 else 0.0,
            'min': round(min(values), 6), 'max': round(max(values), 6)}


def aggregate(reports):
    """Per-arm behavior across repeated samples of the same case.

    A single run is one sample of a stochastic model; counts plus cost mean/sd
    are what a comparison may be based on.
    """
    table = {}
    for report in reports:
        for arm, row in report['arms'].items():
            use = row.get('usage') or {}
            comp = use.get('compression') or {}
            res = use.get('resume') or {}
            cell = table.setdefault(report['case'], {}).setdefault(arm, {
                'runs': 0, 'success': 0, 'required_hit': 0, 'required_total': 0,
                'extra': 0, 'violations': 0, 'fetched': 0, 'fetch_hit': 0,
                'causes': [], 'costs': [], 'bytes': [],
                'comp_costs': [], 'res_costs': [],
                'comp_reason': [], 'res_reason': [],
                'comp_prompt': [], 'comp_completion': [],
                'res_prompt': [], 'res_completion': []})
            cell['runs'] += 1
            cell['success'] += int(bool(row['success']))
            cell['required_hit'] += row['required_hit']
            cell['required_total'] += row['required_total']
            cell['extra'] += row['extra']
            cell['violations'] += row['violations']
            cell['fetched'] += int(bool(row['fetched']))
            cell['fetch_hit'] += int(bool(row['fetch_hit']))
            cell['costs'].append(comp.get('cost', 0.0) + res.get('cost', 0.0))
            cell['comp_costs'].append(comp.get('cost', 0.0))
            cell['res_costs'].append(res.get('cost', 0.0))
            cell['bytes'].append(row['bytes'])
            cell['comp_prompt'].append(comp.get('prompt_tokens', 0))
            cell['comp_completion'].append(comp.get('completion_tokens', 0))
            cell['comp_reason'].append(comp.get('reasoning_tokens', 0))
            cell['res_reason'].append(res.get('reasoning_tokens', 0))
            cell['res_prompt'].append(res.get('prompt_tokens', 0))
            cell['res_completion'].append(res.get('completion_tokens', 0))
            if not row['success']:
                cell['causes'].append((row.get('attribution') or {}).get('classification'))
    for arms in table.values():
        for cell in arms.values():
            cell['cost'] = _spread(cell['costs'])
            cell['comp_cost'] = _spread(cell['comp_costs'])
            cell['resume_cost'] = _spread(cell['res_costs'])
            cell['comp_reasoning'] = _spread(cell['comp_reason'])
            cell['resume_reasoning'] = _spread(cell['res_reason'])
            cell['size'] = _spread(cell['bytes'])
            cell['success_rate'] = round(cell['success'] / cell['runs'], 3)
    return table


def print_aggregate(table):
    for case, arms in table.items():
        print(f"\n{case}  (repeats={max(cell['runs'] for cell in arms.values())})")
        for arm, cell in arms.items():
            cost = cell['cost']
            print(f"  {arm:<11} success {cell['success']}/{cell['runs']}  required "
                  f"{cell['required_hit']}/{cell['required_total']}  extra {cell['extra']}  "
                  f"violations {cell['violations']}  fetched {cell['fetched']}  "
                  f"fetch_hit {cell['fetch_hit']}  bytes {cell['size']['mean']:.0f}"
                  f"±{cell['size']['sd']:.0f}  cost Y{cost['mean']:.4f}±{cost['sd']:.4f} "
                  f"(Y{cost['min']:.4f}–Y{cost['max']:.4f}, resume "
                  f"Y{cell['resume_cost']['mean']:.4f}±{cell['resume_cost']['sd']:.4f})  "
                  f"reason comp {cell['comp_reasoning']['mean']:.0f}"
                  f"±{cell['comp_reasoning']['sd']:.0f} / resume "
                  f"{cell['resume_reasoning']['mean']:.0f}"
                  f"±{cell['resume_reasoning']['sd']:.0f}"
                  + (f"  failed-because {cell['causes']}" if cell['causes'] else ''))


def self_check():
    # The next banner must be the only difference from nosig; a shared contract
    # is what makes the two arms comparable.
    for arm in ('wsc_nosig', 'wsc_next'):
        assert resume_prompt(arm, 'State:') == resume_contract(False)
        assert resume_prompt(arm, 'Observed values (authoritative):') == resume_contract(True)
    case = resume_cases.pending_check_case()
    perfect = {'actions': [{'tool': 'run', 'command': 'python -m unittest tests.test_limiter'}]}
    assert score(perfect, case['required'], case['forbidden'])['success']
    missing = score({'actions': [{'tool': 'edit', 'file': 'src/limiter.py', 'content': 'x'}]},
                    case['required'], case['forbidden'])
    assert not missing['success'] and missing['violations'] == 1
    extra = score({'actions': [{'tool': 'run',
                                'command': 'python -m unittest tests.test_limiter'},
                               {'tool': 'run', 'command': 'ls'}]},
                  case['required'], case['forbidden'])
    assert extra['success'] and extra['extra'] == 1
    reverse = resume_cases.reversed_requirement_case()
    old = {'actions': [{'tool': 'edit', 'file': 'src/exporter.py',
                        'content': 'def export(data):'}]}
    new = {'actions': [{'tool': 'edit', 'file': 'src/exporter.py',
                        'content': 'async def export(data):'}]}
    assert not score(old, reverse['required'], reverse['forbidden'])['success']
    assert score(new, reverse['required'], reverse['forbidden'])['success']
    hidden = resume_cases.hidden_value_case()
    guess = {'actions': [{'tool': 'edit', 'file': 'src/share.py', 'content': 'token = None'}]}
    assert not score(guess, hidden['required'], hidden['forbidden'])['success']
    class FetchModel:
        def chat(self, messages, max_tokens=4096, label=''):
            if 'Fetched' in messages[-1]['content']:
                return {'text': json.dumps({'actions': [
                    {'tool': 'edit', 'file': 'src/share.py', 'content': 'token = SHARE-9'}]}),
                    'usage': {}, 'finish': 'stop'}
            return {'text': json.dumps({'actions': [{'tool': 'fetch', 'key': 'E3'}]}),
                    'usage': {}, 'finish': 'stop'}
    parsed, fetched, hit = resume_call(FetchModel(), 'state', {'E3': "token: SHARE-9"}, {},
                                       hidden['secret'], 'self-check')
    assert fetched and hit and score(parsed, hidden['required'], hidden['forbidden'])['success']

    # A batch of keys is resolved in one turn and every value reaches the model.
    class BatchModel:
        def __init__(self):
            self.sent = []
        def chat(self, messages, max_tokens=4096, label=''):
            self.sent.append(messages[-1]['content'])
            if len(self.sent) == 1:
                return {'text': json.dumps({'actions': [
                    {'tool': 'fetch', 'key': 'E3'}, {'tool': 'fetch', 'key': 'E7'}]}),
                    'usage': {}, 'finish': 'stop'}
            return {'text': json.dumps({'actions': [
                {'tool': 'edit', 'file': 'src/share.py',
                 'content': 'token = SHARE-9, limit = LIM-7'}]}),
                'usage': {}, 'finish': 'stop'}
    batch = BatchModel()
    parsed, fetched, hit = resume_call(batch, 'state',
                                       {'E3': 'token: SHARE-9', 'E7': 'limit: LIM-7'},
                                       {}, None, 'batch')
    assert fetched and len(batch.sent) == 2
    assert 'SHARE-9' in batch.sent[1] and 'LIM-7' in batch.sent[1]
    assert parsed['actions'][0]['file'] == 'src/share.py'

    # Fetch and read in the same turn both resolve before the final actions.
    class MixedModel:
        def __init__(self):
            self.sent = []
        def chat(self, messages, max_tokens=4096, label=''):
            self.sent.append(messages[-1]['content'])
            if len(self.sent) == 1:
                return {'text': json.dumps({'actions': [
                    {'tool': 'fetch', 'key': 'E3'},
                    {'tool': 'read', 'file': 'src/flags.py'}]}),
                    'usage': {}, 'finish': 'stop'}
            return {'text': json.dumps({'actions': [
                {'tool': 'edit', 'file': 'CHANGELOG.md', 'content': 'FEATURE_X'}]}),
                'usage': {}, 'finish': 'stop'}
    mixed = MixedModel()
    resume_call(mixed, 'state', {'E3': 'token: SHARE-9'},
                {'src/flags.py': 'FEATURE_X = "FEATURE_X"\n'}, None, 'mixed')
    assert 'Fetched E3' in mixed.sent[1] and 'Read src/flags.py' in mixed.sent[1]
    assert 'FEATURE_X = "FEATURE_X"' in mixed.sent[1]

    # The three-turn cap holds even when the model keeps asking for evidence.
    class LoopModel:
        def __init__(self):
            self.sent = []
        def chat(self, messages, max_tokens=4096, label=''):
            self.sent.append(messages[-1]['content'])
            return {'text': json.dumps({'actions': [{'tool': 'fetch', 'key': 'E3'}]}),
                    'usage': {}, 'finish': 'stop'}
    loop = LoopModel()
    parsed, fetched, hit = resume_call(loop, 'state', {'E3': 'token: SHARE-9'},
                                       {}, None, 'cap')
    assert len(loop.sent) == 3
    assert 'No more evidence can be returned' in loop.sent[-1]
    assert parsed['actions'][0]['tool'] == 'fetch'

    # An unknown key is reported back, not raised.
    class UnknownModel:
        def __init__(self):
            self.sent = []
        def chat(self, messages, max_tokens=4096, label=''):
            self.sent.append(messages[-1]['content'])
            if len(self.sent) == 1:
                return {'text': json.dumps({'actions': [{'tool': 'fetch', 'key': 'E99'}]}),
                        'usage': {}, 'finish': 'stop'}
            return {'text': json.dumps({'actions': [
                {'tool': 'edit', 'file': 'src/share.py', 'content': 'SHARE-9'}]}),
                'usage': {}, 'finish': 'stop'}
    unknown = UnknownModel()
    parsed, fetched, hit = resume_call(unknown, 'state', {}, {}, None, 'unknown')
    assert fetched and not hit and 'no such key' in unknown.sent[1]
    class RelModel:
        def __init__(self):
            self.calls = []
        def chat(self, messages, max_tokens=4096, label=''):
            self.calls.append({'label': label})
            return {'text': json.dumps({'entries': [
                {'kind': 'fact', 'text': 'src/limiter.py: retries = 5', 'cites': [1]}]}),
                'usage': {}, 'finish': 'stop'}
    case = resume_cases.pending_check_case()
    model = RelModel()
    rel = wsc_chain(model, case, [case['items'], case['round2']['items']], 4096, rel=True)
    assert rel['presented']
    assert any(':rel-distill-' in call['label'] for call in model.calls)
    assert not needs_distillation([{'type': 'message', 'role': 'user',
                                    'content': [{'type': 'input_text', 'text': 'Continue.'}]}])
    assert needs_distillation([{'type': 'message', 'role': 'user',
                                'content': [{'type': 'input_text', 'text': 'Change: use async.'}]}])
    # C: a recorded next action gets its own line; a missing one stays unknown.
    state = {'done': [], 'open': [], 'next': ['add FEATURE_X to CHANGELOG.md'],
             'unknown': []}
    flat = live.passage_text([], [], state, [], [], 4096)
    banner = live.passage_text([], [], state, [], [], 4096, next_banner=True)
    assert 'next: add FEATURE_X' in flat
    assert 'Next action (recorded): add FEATURE_X' in banner
    assert 'next: add FEATURE_X' not in banner
    missing = {'done': [], 'open': ['req#1; no edit to CHANGELOG.md found'],
               'next': [], 'unknown': ['next action not recorded for the open item']}
    assert 'Next action' not in live.passage_text([], [], missing, [], [], 4096,
                                                  next_banner=True)

    # B: the diagnostic arm never applies a revision.
    class ReviseModel:
        def __init__(self):
            self.calls = []
        def chat(self, messages, max_tokens=4096, label=''):
            self.calls.append({'label': label})
            if 'Current relations:' in messages[-1]['content']:
                return {'text': json.dumps({'entries': [], 'revise': [
                    {'ref': 'w1-1@1', 'text': 'src/x.py: y = 2', 'cites': [1]}]}),
                    'usage': {}, 'finish': 'stop'}
            return {'text': json.dumps({'entries': [
                {'kind': 'fact', 'text': 'src/x.py: y = 1', 'cites': [1]}]}),
                'usage': {}, 'finish': 'stop'}
    nored_case = resume_cases.pending_check_case()
    nored_model = ReviseModel()
    nored = wsc_chain(nored_model, nored_case, [nored_case['items'],
                                                nored_case['round2']['items']],
                      4096, lean=True, ext=True, gate=True, norevise=True,
                      family='nored')
    assert 'src/x.py: y = 1' in nored['presented']
    assert 'src/x.py: y = 2' not in nored['presented']
    assert any(':nored-distill-' in call['label'] for call in nored_model.calls)

    long_case = resume_cases.long_hidden_case()
    eco_model = RelModel()
    eco = wsc_chain(eco_model, long_case, long_case['rounds'], 4096,
                    lean=True, rel=True, gate=True)
    assert eco['presented']
    assert len(eco_model.calls) < len(long_case['rounds'])
    assert any(':eco-distill-' in call['label'] for call in eco_model.calls)

    # Several threshold compactions in one session keep the recorded next once.
    multi_rounds = [[
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Requirement: rename the feature flag to FEATURE_X in src/flags.py.'}]},
        resume_cases._call('e1', 'edit', {'file_path': 'src/flags.py',
                                          'old_string': 'FEATURE_OLD',
                                          'new_string': 'FEATURE_X'}),
        resume_cases._output('e1', 'ok'),
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text',
            'text': 'Rename done. Next: verify docs/relnotes.md.'}]},
    ]]
    for number in range(2, 25):
        multi_rounds.append([
            {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text',
                                                             'text': 'Continue.'}]},
            resume_cases._call(f'm{number}', 'read',
                               {'file_path': f'docs/note-{number}.md'}),
            resume_cases._output(f'm{number}', f'note {number}: ' + 'context ' * 40),
        ])
    class MultiModel:
        def __init__(self):
            self.calls = []
        def chat(self, messages, max_tokens=4096, label=''):
            self.calls.append({'label': label, 'sent': messages[-1]['content']})
            return {'text': json.dumps({'entries': [
                {'kind': 'fact', 'text': f'note {len(self.calls)}: context retained',
                 'cites': [1]}]}), 'usage': {}, 'finish': 'stop'}
    multi_model = MultiModel()
    multi = wsc_chain(multi_model, {'case': 'multi-compaction'}, multi_rounds, 4096,
                      lean=True, ext=True, threshold_chars=1200, family='nosig')
    compacted = {re.search(r'-distill-r(\d+)$', call['label']).group(1)
                 for call in multi_model.calls}
    assert len(compacted) >= 2
    assert multi['presented'].count('next: verify docs/relnotes.md') == 1
    print('resume self-check ok')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path,
                        default=ROOT / 'benchmarks' / 'coding_compaction_v1' / 'runs')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--arms', default=','.join(DEFAULT_ARMS),
                        help='comma-separated subset of arms to run')
    parser.add_argument('--case', default='',
                        help='comma-separated case names; default is every case in the suite')
    parser.add_argument('--long', action='store_true',
                        help='six-round scenarios: assistant-only next step, late reversal, distant value')
    parser.add_argument('--repeat', type=int, default=1,
                        help='independent samples per case; single runs are not a comparison')
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args(argv)
    if args.self_check:
        return self_check()
    arms = [name.strip() for name in args.arms.split(',') if name.strip()]
    allowed = {'dsh_native', 'wsc', 'wsc_lean', 'wsc_rel', 'wsc_lrel', 'wsc_eco',
               'wsc_ext', 'wsc_gate', 'wsc_tank', 'wsc_gatex', 'wsc_gater',
               'wsc_both', 'wsc_nosig', 'wsc_nosig_v1', 'wsc_nored', 'wsc_next',
               'wsc_thin'}
    unknown = [name for name in arms if name not in allowed]
    if unknown:
        raise SystemExit(f'unknown arms: {unknown}')
    out = args.out / ('resume-' + time.strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True, exist_ok=True)
    # One Model per sample: its response cache must not collapse repeats into
    # copies of the first answer.
    models = {number: live.Model(live.load_key()) for number in range(args.repeat)}
    factories = resume_cases.LONG_CASES if args.long else resume_cases.CASES
    if args.case:
        wanted = {name.strip() for name in args.case.split(',') if name.strip()}
        factories = tuple(factory for factory in factories if factory()['case'] in wanted)
        if not factories:
            raise SystemExit(f'no case matched: {sorted(wanted)}')
    cases = [factory() for factory in factories]
    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [(number, case, pool.submit(
            measure, models[number - 1], case, out, arms,
            '' if args.repeat == 1 else f'repeat-{number}'))
            for number in range(1, args.repeat + 1) for case in cases]
        for number, case, future in futures:
            report = future.result()
            report['repeat'] = number
            results.append(report)
            print(f"\n[{case['case']} r{number}]")
            for arm in arms:
                row = report['arms'][arm]
                use = row.get('usage') or {}
                comp, res = use.get('compression') or {}, use.get('resume') or {}
                print(f"  {arm:<11} success {int(row['success'])}  required "
                      f"{row['required_hit']}/{row['required_total']}  extra {row['extra']}  "
                      f"violations {row['violations']}  fetched {row['fetched']}  "
                      f"fetch_hit {row['fetch_hit']}  grounded {row.get('grounded')}  "
                      f"bytes {row['bytes']}  "
                      f"tokens {comp.get('prompt_tokens', 0)}/{comp.get('completion_tokens', 0)}"
                      f"+{res.get('prompt_tokens', 0)}/{res.get('completion_tokens', 0)}  "
                      f"cost Y{comp.get('cost', 0.0) + res.get('cost', 0.0):.4f}"
                      + ('' if row['success'] else
                         f"  cause {(row.get('attribution') or {}).get('classification')}"))
    table = aggregate(results)
    (out / 'summary.json').write_text(json.dumps({'model': live.MODEL,
                                                  'repeats': args.repeat,
                                                  'results': results,
                                                  'aggregate': table},
                                                ensure_ascii=False, indent=2), encoding='utf-8')
    print_aggregate(table)
    print('\noutput', out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
