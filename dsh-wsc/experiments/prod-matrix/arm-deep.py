"""Deep per-run metrics for the final arm comparison.

Every number is derived from the saved session and journal; nothing is inferred
from the model's prose. Proxies are named in the output so a reader can tell
what each one does and does not prove.

  cost          main-session + extraction, CNY (1.0/0.02/4.0 per M)
  wall          first round .bat to last round .jsonl (file mtimes)
  compress      final checkpoint chars / (shadowed tokens at that compaction x 4)
  verbatim      round tasks found word-for-word in the final checkpoint
  coverage      work requests with an edit recorded after they were stated
  rework        edits that repeat an earlier edit's (path, new text)
  reread        reads of a path read before the last compaction, unedited since
  citations     `edit #a; check #b` lines whose seqs resolve to edit/result events
  envrefs       runtime spill/temp paths quoted inside checkpoints
  errors        failed tool results
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import io
import json
import os
import re
import statistics
from pathlib import Path

import zstandard

HERE = Path(__file__).resolve().parent
RUNS = HERE / 'runs'
SCEN = HERE / 'scenarios'
SESSIONS = Path(os.environ.get('DSH_HOME', str(Path.home() / '.dsh'))) / 'sessions'
JOURNALS = Path(os.environ.get('DSH_HOME', str(Path.home() / '.dsh'))) / 'wsc' / 'nosig'
CHECK = re.compile(r'edited at #(\d+); the check at #(\d+)')
ENV = re.compile(r'dsh-spill-|AppData[\\/]Local[\\/]Temp|out[\\/]round-\d+\.(?:jsonl|txt)')
FILE_PATH = re.compile(r'[A-Za-z0-9_./\\-]+\.(?:py|js|mjs|ts|tsx|json|md|yml|yaml|cjs)')
ERROR_HEAD = re.compile(r'^(?:eperm|eacces|enoent|not ok\b|[x\u00d7\u2716]\s+\S|'
                        r'[a-z]*error\b|exception\b|traceback\b|fatal\b|unhandled\b)', re.I)

spec = importlib.util.spec_from_file_location('oracle', HERE / 'oracle-long40.py')
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def load_events(session: str) -> list[dict]:
    matches = glob.glob(str(SESSIONS / '*' / session / 'session.v4.jsonl.zstd'))
    if not matches:
        return []
    with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(open(matches[0], 'rb').read())) as reader:
        return [json.loads(line) for line in reader.read().decode('utf-8').splitlines() if line.strip()]


def args_of(event: dict) -> dict:
    args = (event.get('data') or {}).get('arguments')
    if isinstance(args, dict):
        return args
    try:
        return json.loads(args or '{}')
    except Exception:
        return {}


def text_of(message: dict) -> str:
    content = (message or {}).get('content') or []
    if not isinstance(content, list):
        return ''
    return '\n'.join(part.get('text', '') for part in content if isinstance(part, dict))


def normalize(text: str) -> str:
    value = re.sub(r'^headless\s+', '', str(text or ''), flags=re.I)
    return re.sub(r'\s+', ' ', value).strip()


def wall_seconds(directory: Path) -> float:
    starts = [p.stat().st_mtime for p in (directory / 'out').glob('round-*.bat')]
    ends = [p.stat().st_mtime for p in (directory / 'out').glob('round-*.jsonl')]
    if not starts or not ends:
        return 0.0
    return max(ends) - min(starts)


def tool_events(events: list[dict]):
    for event in events:
        kind = event.get('type')
        if kind == 'tool/call':
            data = event.get('data') or {}
            payload = args_of(event)
            payload['__turn'] = data.get('turn')
            yield event.get('seq'), 'call', data.get('name'), payload
        elif kind == 'tool/result':
            data = event.get('data') or {}
            message = data.get('message') or {}
            meta = data.get('meta') or {}
            yield event.get('seq'), 'result', None, {'text': text_of(message), 'isError': meta.get('isError')}


def run_metrics(scenario: str, arm: str, rep: int) -> dict | None:
    directory = RUNS / scenario / arm / f'rep{rep}'
    if not (directory / 'done').exists():
        return None
    metrics_path = directory / 'metrics.json'
    metrics = json.loads(metrics_path.read_text(encoding='utf-8')) if metrics_path.exists() else {}
    session = (directory / 'done').read_text(encoding='utf-8').strip()
    events = load_events(session)
    if not events:
        return None
    calls = {}
    edits = []
    reads = []
    errors = 0
    compactions = []
    checkpoints = []
    by_seq = {}
    turn_paths = {}
    for seq, kind, name, payload in tool_events(events):
        if kind == 'call':
            by_seq[seq] = name
            if name in ('edit', 'write'):
                path = payload.get('path') or payload.get('file_path') or ''
                new = payload.get('new_string') if isinstance(payload.get('new_string'), str) else payload.get('content')
                if path:
                    edits.append({'seq': seq, 'path': str(path).replace('\\', '/'), 'new': new or ''})
                    turn = payload.get('__turn')
                    turn_paths.setdefault(turn, []).append(str(path).replace('\\', '/'))
            if name == 'read':
                path = payload.get('path') or payload.get('file_path') or ''
                if path:
                    reads.append((seq, str(path).replace('\\', '/')))
        else:
            by_seq[seq] = 'result'
            text = payload.get('text') or ''
            first = next((line.strip() for line in text.splitlines() if line.strip()), '')
            if payload.get('isError') is True or (first and not first.startswith('<') and ERROR_HEAD.match(first)):
                errors += 1
    for event in events:
        kind = event.get('type')
        if kind == 'compaction/start':
            compactions.append(event.get('seq'))
        elif kind == 'compaction/summary':
            text = ''.join(block.get('text', '') for block in (event.get('data') or {}).get('summary') or []
                           if block.get('type') == 'text')
            checkpoints.append({'seq': event.get('seq'), 'text': text,
                                'shadowed': (event.get('data') or {}).get('shadowedTokenCount') or 0})
        elif kind == 'assistant/message':
            names = [block.get('name') for block in ((event.get('data') or {}).get('message') or {}).get('content') or []
                     if block.get('type') == 'tool-call']
            by_seq[event.get('seq')] = names[0] if names else 'assistant'

    seen_edits = set()
    rework = 0
    for edit in edits:
        key = (edit['path'], edit['new'].strip())
        if key in seen_edits:
            rework += 1
        else:
            seen_edits.add(key)

    compaction_seqs = sorted(seq for seq in compactions if isinstance(seq, int))
    reread = 0
    for seq, path in reads:
        previous = [c for c in compaction_seqs if c < seq]
        if not previous:
            continue
        boundary = previous[-1]
        earlier = [s for s, p in reads if p == path and s < boundary]
        if not earlier:
            continue
        edited_since = any(e['path'] == path and earlier[-1] < e['seq'] <= seq for e in edits)
        if not edited_since:
            reread += 1

    final = checkpoints[-1] if checkpoints else {'text': '', 'shadowed': 0}
    rounds = json.loads((SCEN / scenario / 'rounds.json').read_text(encoding='utf-8'))
    flat = normalize(final['text'])
    verbatim = sum(1 for task in rounds if normalize(task) not in ('', 'continue') and normalize(task) in flat)

    # Forbidden-work rounds: the request names files it does not want touched.
    forbidden_rounds = forbidden_edits = 0
    offtask = 0
    for number, task in enumerate(rounds, 1):
        edited = turn_paths.get(number, [])
        text = normalize(task)
        if re.search(r'\bdo not (?:change|modify) (?:source )?files?\b', text, re.I):
            forbidden_rounds += 1
            hits = [path for path in edited if path.startswith('src/')]
            forbidden_edits += len(hits)
        named = {p.replace('\\', '/').lower() for p in FILE_PATH.findall(text)}
        named |= {f'{m.lower()}.md' for m in re.findall(r'\b(README|CHANGELOG)\b', text)}
        if not named:
            continue
        for path in edited:
            lower = path.lower()
            if lower.startswith('tests/'):
                continue
            if not any(lower == p or lower.endswith('/' + p) for p in named):
                offtask += 1

    citations = valid = 0
    envrefs = 0
    for checkpoint in checkpoints:
        envrefs += len(ENV.findall(checkpoint['text']))
        for edit, check in CHECK.findall(checkpoint['text']):
            citations += 1
            if by_seq.get(int(edit)) in ('edit', 'write') and by_seq.get(int(check)) in ('result', 'pwsh', 'shell', 'cmd'):
                valid += 1

    covered = work = 0
    journal = JOURNALS / f'{session}.jsonl'
    if journal.exists():
        rows = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines() if line.strip()]
        controls = [row for row in rows if row.get('op') == 'control']
        receipts = [row['receipt'] for row in rows if row.get('op') == 'receipt']
        action = re.compile(r'\b(add|change|update|fix|implement|refactor|remove|rename|create|write|wire|'
                            r'make|use|set|limit|support|sort|validate|export|replace)\b', re.I)
        negated = re.compile(r"\b(?:do not|don't|without)\s+(?:change|modify|edit)\b", re.I)

        def normalize_term(term: str) -> str:
            value = re.sub(r'^--', '', str(term))
            value = re.sub(r'([a-z0-9])([A-Z])', r'\1-\2', value).lower()
            return re.sub(r'[^a-z0-9-]', '', value)

        def path_like(term: str) -> bool:
            return '/' in term or '\\' in term or bool(re.search(r'\.[a-z0-9]{1,5}$', term, re.I))

        for control in controls:
            text = control.get('text', '')
            seq = control.get('seq')
            if not action.search(negated.sub('', text)):
                continue
            work += 1
            paths = {p.replace('\\', '/').lower() for p in FILE_PATH.findall(text)}
            paths |= {f'{m.lower()}.md' for m in re.findall(r'\b(README|CHANGELOG)\b', text)}
            terms = {normalize_term(t) for t in re.findall(r'[A-Za-z_$][A-Za-z0-9_$]*|--[a-z][a-z0-9-]+', text)
                     if len(t) > 2 and not path_like(t)}
            hit = False
            for receipt in receipts:
                if not (isinstance(seq, int) and isinstance(receipt.get('edit'), int) and receipt['edit'] > seq):
                    continue
                path = str(receipt.get('path') or '').replace('\\', '/').lower()
                if any(path == p or path.endswith('/' + p) for p in paths):
                    hit = True
                    break
                if terms & {normalize_term(t) for t in receipt.get('terms') or []}:
                    hit = True
                    break
            covered += 1 if hit else 0

    grade, total = (0, 0)
    if scenario == 'long-40' and (directory / 'ws').exists():
        results = oracle.checks(directory / 'ws')
        grade = sum(1 for _, ok, _ in results if ok)
        total = len(results)

    return {
        'scenario': scenario, 'arm': arm, 'rep': rep, 'session': session,
        'cost': metrics.get('totalCostCny'), 'main': metrics.get('costCny'),
        'ext': metrics.get('extractionCostCny'), 'compactions': metrics.get('compactions'),
        'steps': metrics.get('steps'), 'tools': metrics.get('toolCalls'),
        'testsPassed': metrics.get('testsPassed'), 'testsFailed': metrics.get('testsFailed'),
        'probe': f"{metrics.get('probePassed')}/{metrics.get('probeTotal')}",
        'wall': round(wall_seconds(directory), 1),
        'cpFinal': len(final['text']), 'cpMax': max((len(c['text']) for c in checkpoints), default=0),
        'compress': round(len(final['text']) / max(1, final['shadowed'] * 4), 3) if final['shadowed'] else None,
        'verbatim': f"{verbatim}/{len(rounds)}",
        'coverage': f"{covered}/{work}" if work else '-',
        'rework': rework, 'edits': len(edits), 'reread': reread, 'reads': len(reads),
        'offtask': offtask, 'forbidden': f"{forbidden_edits}/{forbidden_rounds}",
        'citations': f"{valid}/{citations}" if citations else '-',
        'envrefs': envrefs, 'errors': errors, 'oracle': f"{grade}/{total}" if total else '-',
        'checkpoints': len(checkpoints),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenario', default='long-40')
    parser.add_argument('--arms', default='native,w80,v2f,v3r')
    parser.add_argument('--save', action='store_true')
    args = parser.parse_args()
    out = []
    for arm in [a.strip() for a in args.arms.split(',') if a.strip()]:
        for rep_dir in sorted((RUNS / args.scenario / arm).glob('rep*')):
            rep = int(rep_dir.name[3:])
            row = run_metrics(args.scenario, arm, rep)
            if row is None:
                continue
            out.append(row)
            if args.save:
                (rep_dir / 'deep.json').write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding='utf-8')
            print(json.dumps(row, ensure_ascii=False))
    if not out:
        return
    print('\nMEDIANS')
    for arm in sorted({row['arm'] for row in out}):
        sel = [row for row in out if row['arm'] == arm]
        def med(key):
            values = [row[key] for row in sel if isinstance(row[key], (int, float))]
            return f"{statistics.median(values):.2f}" if values else '-'
        print(f"{arm}: n={len(sel)} cost={med('cost')} main={med('main')} ext={med('ext')} "
              f"comps={med('compactions')} wall={med('wall')} steps={med('steps')} "
              f"cpFinal={med('cpFinal')} compress={med('compress')} "
              f"rework={med('rework')} reread={med('reread')}/{med('reads')} errors={med('errors')}")


if __name__ == '__main__':
    main()
