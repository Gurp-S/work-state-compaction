"""Counterfactual scan over the v2f base: where checkpoint bytes and steps go,
and what each proposed mechanism could save. No model calls.
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

import zstandard

RUNS = Path(__file__).resolve().parent / 'runs' / 'long-40'
SESSIONS = Path(os.environ.get('DSH_HOME', str(Path.home() / '.dsh'))) / 'sessions'
JOURNALS = Path(os.environ.get('DSH_HOME', str(Path.home() / '.dsh'))) / 'wsc' / 'nosig'
PATH_RE = re.compile(r'[A-Za-z0-9_./\\-]+\.(?:py|js|mjs|ts|tsx|json|md|yml|yaml|cjs)')
KIND = re.compile(r'^(?:constraint|requirement|decision|context|verification|fact)\s*:\s*', re.I)
ACTION = re.compile(r'\b(add|change|update|fix|implement|refactor|remove|rename|create|write|wire|make|use|set|'
                    r'limit|support|sort|validate|export|replace|document|keep)\b', re.I)


def load_session(session: str) -> list[dict]:
    matches = glob.glob(str(SESSIONS / '*' / session / 'session.v4.jsonl.zstd'))
    if not matches:
        return []
    with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(open(matches[0], 'rb').read())) as reader:
        return [json.loads(line) for line in reader.read().decode('utf-8').splitlines() if line.strip()]


def result_text(message: dict) -> str:
    return '\n'.join(part.get('text', '') for part in (message.get('content') or [])
                     if isinstance(part, dict))


def norm(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip().lower()


def journal(session: str) -> list[dict]:
    path = JOURNALS / f'{session}.jsonl'
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def entries(rows: list[dict]) -> list[dict]:
    live = {}
    order = []
    for row in rows:
        if row.get('op') == 'add':
            live[row['entry']['id']] = dict(row['entry'])
            order.append(row['entry']['id'])
        elif row.get('op') == 'revise' and row.get('entry', {}).get('id') in live:
            live[row['entry']['id']].update(row['entry'])
        elif row.get('op') == 'supersede':
            for entry_id in row.get('ids') or []:
                if entry_id in live:
                    live[entry_id]['status'] = 'superseded'
    return [live[entry_id] for entry_id in order if live[entry_id].get('status', 'active') == 'active']


def checkpoint_texts(events: list[dict]) -> list[str]:
    return [''.join(block.get('text', '') for block in (event.get('data') or {}).get('summary') or []
                    if block.get('type') == 'text')
            for event in events if event.get('type') == 'compaction/summary']


def sections(text: str) -> dict:
    quotes = re.findall(r'^\d+\. "([^\n]*)"', text, re.M)
    ledger = re.findall(r'^- (.+)$', text, re.M)
    index_line = re.search(r'^Evidence index.*$', text, re.M)
    value_line = re.search(r'^Observed values.*$', text, re.M)
    values = re.findall(r'\[V\d+\] (.+?) \(read_evidence #\d+\)', value_line.group(0)) if value_line else []
    recent = re.search(r'## Recent changes\n([\s\S]*?)(?:\n\n|$)', text)
    state = re.search(r'## Current state[\s\S]*?(?=## Recent changes|Checks:|$)', text)
    checks = re.search(r'^Checks:.*$', text, re.M)
    return {
        'quotes': quotes, 'ledger': ledger, 'values': values,
        'index': index_line.group(0) if index_line else '',
        'valueLine': value_line.group(0) if value_line else '',
        'recent': recent.group(1) if recent else '',
        'state': state.group(0) if state else '',
        'checks': checks.group(0) if checks else '',
        'bytes': len(text),
    }


def main() -> None:
    for directory in sorted(RUNS.glob('v2f/rep*')):
        if not (directory / 'done').exists():
            continue
        session = (directory / 'done').read_text(encoding='utf-8').strip()
        events = load_session(session)
        texts = checkpoint_texts(events)
        last = sections(texts[-1]) if texts else sections('')
        rows = journal(session)
        active = entries(rows)
        adds = [row['entry'] for row in rows if row.get('op') == 'add']
        controls = [row for row in rows if row.get('op') == 'control']
        values = [row['value'] for row in rows if row.get('op') == 'value']
        receipts = [row['receipt'] for row in rows if row.get('op') == 'receipt']

        quote_norm = [norm(q) for q in last['quotes']]
        ledger_dup = ledger_dup_bytes = 0
        for line in last['ledger']:
            core = norm(KIND.sub('', line))
            if len(core) < 30:
                continue
            if any(core in quote for quote in quote_norm):
                ledger_dup += 1
                ledger_dup_bytes += len(line.encode())
        quote_core = ' '.join(quote_norm)

        # Extraction duplicates: an add that restates an earlier entry verbatim.
        seen = set()
        dup_adds = dup_add_bytes = 0
        for entry in adds:
            text = norm(KIND.sub('', entry.get('text', '')))
            if text in seen:
                dup_adds += 1
                dup_add_bytes += len(entry.get('text', '').encode())
            seen.add(text)

        # Stale facts: path edited after the newest cite recorded on the entry.
        last_edit = {}
        for event in events:
            data = event.get('data') or {}
            if event.get('type') == 'tool/call' and data.get('name') in ('edit', 'write'):
                try:
                    args = json.loads(data.get('arguments') or '{}')
                except Exception:
                    args = {}
                path = args.get('path') or args.get('file_path')
                if isinstance(path, str):
                    last_edit[path] = max(last_edit.get(path, 0), event.get('seq') or 0)
        stale = stale_bytes = 0
        for entry in active:
            cites = entry.get('cites') or []
            paths = set(PATH_RE.findall(entry.get('text', '')))
            if not paths:
                continue
            entry_turn = max([data for data in cites if isinstance(data, int)] or [0])
            if any(last_edit.get(path, 0) > entry_turn for path in paths):
                stale += 1
                stale_bytes += len(entry.get('text', '').encode())

        # Repeat reads and their bytes (per read result).
        calls = {}
        reads = []
        compactions = []
        for event in events:
            data = event.get('data') or {}
            kind = event.get('type')
            if kind == 'tool/call':
                try:
                    args = json.loads(data.get('arguments') or '{}')
                except Exception:
                    args = {}
                calls[data.get('callId')] = {'name': data.get('name'), 'args': args,
                                             'seq': event.get('seq') or 0}
            elif kind == 'tool/result':
                message = data.get('message') or {}
                call_id = message.get('toolCallId') or (message.get('source') or {}).get('callId')
                call = calls.get(call_id)
                if call and call['name'] == 'read':
                    path = call['args'].get('file_path') or call['args'].get('path')
                    text = result_text(message)
                    reads.append((call['seq'], path, text, data.get('turn')))
            elif kind == 'compaction/summary':
                compactions.append(event.get('seq') or 0)
        seen_reads = {}
        repeat_window = repeat_after = repeat_bytes = after_bytes = 0
        for seq, path, text, turn in reads:
            if not isinstance(path, str):
                continue
            key = path.lower()
            last_cp = compactions[-1] if compactions else 0
            if key in seen_reads:
                prev_seq, prev_text, prev_cp = seen_reads[key]
                if prev_text == text:
                    edited = any(last_edit.get(p, 0) > prev_seq for p in last_edit if p.lower() == key)
                    if prev_cp >= last_cp:
                        repeat_window += 1
                        repeat_bytes += len(text.encode())
                    elif not edited:
                        repeat_after += 1
                        after_bytes += len(text.encode())
            seen_reads[key] = (seq, text, last_cp)

        # Requirement status: action requirements with a later edit receipt.
        done_reqs = 0
        for index, control in enumerate(controls):
            text = control.get('text', '')
            if not ACTION.search(text):
                continue
            seq = control.get('seq') or 0
            paths = set(PATH_RE.findall(text))
            later = [r for r in receipts if r.get('edit', 0) > seq and
                     (not paths or r.get('path') in paths)]
            if later:
                done_reqs += 1

        # Envelope and gutter overhead across read results.
        envelope = gutter = total = 0
        for _, _, text, _ in reads:
            total += len(text.encode())
            envelope += len(re.findall(r'</?(?:path|type|content)>', text)) * 6
            gutter += sum(len(match) for match in re.findall(r'^\d+: ', text, re.M))
        index_rows = len(re.findall(r'\[E\d+\]', last['index']))
        values_shown = len(last['values'])
        archived = re.search(r'(\d+) older values archived', last['valueLine'])
        values_dropped = int(archived.group(1)) if archived else max(0, len(values) - values_shown)
        prose_ledger = [line for line in last['ledger'] if not re.search(r'[=`]|--[a-z]|\d', line)]

        print(f"\n== {directory.name} session={session[:18]}.. checkpoints={len(texts)}")
        print(f"  cp bytes={last['bytes']} quotes={len(last['quotes'])}/{sum(len(q.encode()) for q in last['quotes'])}B "
              f"ledger={len(last['ledger'])}/{sum(len(l.encode()) for l in last['ledger'])}B "
              f"values={values_shown}/{len(last['valueLine'].encode())}B index={index_rows}/{len(last['index'].encode())}B "
              f"state={len(last['state'].encode())}B recent={len(last['recent'].encode())}B checks={len(last['checks'].encode())}B")
        print(f"  P4 cross-section: ledger duplicating a quote={ledger_dup} lines/{ledger_dup_bytes}B; "
              f"index rows={index_rows} (fetched≈0)")
        print(f"  P3 extraction: adds={len(adds)} exact repeats={dup_adds}/{dup_add_bytes}B of "
              f"{sum(len(e.get('text','').encode()) for e in adds)}B")
        print(f"  P9 stale facts: {stale}/{len(active)} entries, {stale_bytes}B (path edited after cite)")
        print(f"  P2 window repeats: {repeat_window} reads/{repeat_bytes}B; P1 unchanged after compaction: {repeat_after} reads/{after_bytes}B")
        print(f"  P9 envelope={envelope}B gutter={gutter}B of {total}B read bytes")
        print(f"  P6 requirements with later edit receipt: {done_reqs}/{len(controls)} controls")
        print(f"  P7 values: journal={len(values)} shown={values_shown} dropped={values_dropped}; prose ledger={len(prose_ledger)} lines")


if __name__ == '__main__':
    main()
