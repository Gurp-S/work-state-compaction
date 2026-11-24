"""Quality audit from the raw text: stale checkpoint claims, citation validity,
and requirement coverage. Complements the final-state oracle.
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import re
from pathlib import Path

import zstandard

HERE = Path(__file__).resolve().parent
RUNS = HERE / 'runs' / 'long-40'
SESSIONS = Path(os.environ.get('DSH_HOME', str(Path.home() / '.dsh'))) / 'sessions'
JOURNALS = Path(os.environ.get('DSH_HOME', str(Path.home() / '.dsh'))) / 'wsc' / 'nosig'
PATH_RE = re.compile(r'[A-Za-z0-9_./\\-]+\.(?:py|js|mjs|ts|tsx|json|md|yml|yaml|cjs)')
TOKEN_RE = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*|--[a-z][a-z-]+|\d+\.\d+')
STOP = {'src', 'tests', 'the', 'and', 'with', 'rows', 'test', 'file', 'this', 'that', 'return',
        'returns', 'uses', 'when', 'into', 'from', 'default', 'update', 'adds', 'keeps', 'after',
        'before', 'header', 'sorts', 'counts'}
CHECK = re.compile(r'edited at #(\d+); the check at #(\d+)')


def session_events(session: str) -> list[dict]:
    matches = glob.glob(str(SESSIONS / '*' / session / 'session.v4.jsonl.zstd'))
    if not matches:
        return []
    with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(open(matches[0], 'rb').read())) as reader:
        return [json.loads(line) for line in reader.read().decode('utf-8').splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--arms', default='v2f,v3i,v3x,v3r,v3b')
    args = parser.parse_args()
    for arm in [part.strip() for part in args.arms.split(',') if part.strip()]:
        for directory in sorted((RUNS / arm).glob('rep*')):
            if not (directory / 'done').exists():
                continue
            session = (directory / 'done').read_text().strip()
            events = session_events(session)
            checkpoints = [''.join(block.get('text', '') for block in event['data']['summary']
                                   if block.get('type') == 'text')
                           for event in events if event.get('type') == 'compaction/summary']
            by_seq = {}
            for event in events:
                data = event.get('data') or {}
                seq = event.get('seq')
                if event.get('type') == 'tool/call':
                    by_seq[seq] = data.get('name')
                elif event.get('type') == 'assistant/message':
                    names = [block.get('name') for block in (data.get('message') or {}).get('content') or []
                             if block.get('type') == 'tool-call']
                    by_seq[seq] = names[0] if names else 'assistant'
                elif event.get('type') == 'tool/result':
                    by_seq[seq] = 'result'
            workspace = directory / 'ws'
            stale = claims = 0
            for text in checkpoints:
                for line in re.findall(r'^- (.+)$', text, re.M):
                    core = re.sub(r'^(?:constraint|requirement|decision|context|verification|fact)\s*:\s*', '', line)
                    paths = set(PATH_RE.findall(core))
                    if not paths:
                        continue
                    claims += 1
                    content = ''
                    missing = False
                    for raw in paths:
                        rel = raw.replace('\\', '/')
                        prefix = (directory / 'ws').as_posix().lower() + '/'
                        if rel.lower().startswith(prefix):
                            rel = rel[len(prefix):]
                        candidate = workspace / rel
                        if not candidate.exists():
                            missing = True
                            break
                        content += candidate.read_text(encoding='utf-8', errors='replace')
                    tokens = [token for token in TOKEN_RE.findall(core)
                              if len(token) > 2 and token.lower() not in STOP]
                    if missing or (tokens and not any(token in content for token in tokens)):
                        stale += 1
            citations = valid = 0
            for text in checkpoints:
                for edit, check in CHECK.findall(text):
                    citations += 1
                    edit_ok = by_seq.get(int(edit)) in ('edit', 'write')
                    check_ok = by_seq.get(int(check)) in ('result', 'pwsh', 'shell', 'cmd')
                    if edit_ok and check_ok:
                        valid += 1
            journal_path = JOURNALS / f'{session}.jsonl'
            controls = receipts = 0
            covered = 0
            if journal_path.exists():
                rows = [json.loads(line) for line in journal_path.read_text(encoding='utf-8').splitlines() if line.strip()]
                control_rows = [row for row in rows if row.get('op') == 'control']
                receipt_rows = [row['receipt'] for row in rows if row.get('op') == 'receipt']
                controls = len(control_rows)
                receipts = len(receipt_rows)
                for control in control_rows[1:]:
                    text = control.get('text', '')
                    paths = set(PATH_RE.findall(text))
                    terms = set(TOKEN_RE.findall(text))
                    if any((paths and receipt.get('path') in paths) or
                           (terms & set(receipt.get('terms') or [])) for receipt in receipt_rows):
                        covered += 1
            print(f"{arm}/{directory.name}: staleClaims={stale}/{claims} "
                  f"checkCitations valid={valid}/{citations} "
                  f"coverage={covered}/{max(0, controls - 1)}({receipts} receipts)")


if __name__ == '__main__':
    main()
