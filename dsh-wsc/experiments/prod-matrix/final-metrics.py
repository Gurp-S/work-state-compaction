import glob
import io
import json
import os
import re
import zstandard
from pathlib import Path

RUNS = Path('runs/long-40/v2f')
J = Path(os.environ.get('DSH_HOME', str(Path.home() / '.dsh'))) / 'wsc' / 'nosig'
SESSIONS = J.parent.parent / 'sessions'
KIND = re.compile(r'^(?:constraint|requirement|decision|context|verification|fact)\s*:\s*', re.I)
PATHRE = re.compile(r'[A-Za-z0-9_./\\-]+\.(?:py|js|mjs|ts|tsx|json|md|yml|yaml|cjs)')
TESTISH = re.compile(r'@\s*0\.0|✔|✖|\(\d+(?:\.\d+)?ms\)')


def subject(text: str) -> str:
    text = KIND.sub('', text).strip()
    flags = ' '.join(sorted(set(re.findall(r'--[a-z][a-z-]+', text))))
    match = PATHRE.search(text)
    suffix = '::' + flags if flags else ''
    if match:
        rest = text[match.end():]
        first = re.search(r'[A-Za-z_$][A-Za-z0-9_$]*', rest)
        name = first.group(0).lower() if first else ''
        return match.group(0).lower().replace('\\', '/') + '::' + name + suffix
    call = re.search(r'([A-Za-z_$][A-Za-z0-9_$]*)\s*\(([^)]*)\)', text)
    if call:
        return 'fn:' + call.group(1).lower() + '(' + call.group(2).lower() + ')' + suffix
    return ''


for directory in sorted(RUNS.glob('rep*')):
    if not (directory / 'done').exists():
        continue
    session = (directory / 'done').read_text().strip()
    workspace = directory / 'ws'
    rows = [json.loads(line) for line in open(J / (session + '.jsonl'), encoding='utf-8')]
    live = {}
    order = []
    adds = []
    for row in rows:
        if row.get('op') == 'add':
            entry = row['entry']
            adds.append(entry)
            live[entry['id']] = dict(entry)
            order.append(entry['id'])
        elif row.get('op') == 'revise' and row.get('entry', {}).get('id') in live:
            live[row['entry']['id']].update(row['entry'])
        elif row.get('op') == 'supersede':
            for entry_id in row.get('ids') or []:
                if entry_id in live:
                    live[entry_id]['status'] = 'superseded'
    active = [live[entry_id] for entry_id in order if live[entry_id].get('status', 'active') == 'active']

    seen = {}
    dup = dup_bytes = 0
    add_bytes = 0
    for entry in adds:
        text = entry.get('text', '')
        add_bytes += len(text.encode())
        key = 'TEST' if TESTISH.search(text) else subject(text)
        if key == '':
            continue
        if key in seen:
            dup += 1
            dup_bytes += len(text.encode())
        else:
            seen[key] = text

    stale = stale_bytes = checked = 0
    for entry in active:
        text = entry.get('text', '')
        paths = set(PATHRE.findall(text))
        if not paths:
            continue
        checked += 1
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
        if missing:
            stale += 1
            stale_bytes += len(text.encode())
            continue
        tokens = [token for token in re.findall(r'[A-Za-z_$][A-Za-z0-9_$]*|--[a-z][a-z-]+|\d+\.\d+', text)
                  if len(token) > 2 and token.lower() not in {
                      'src', 'tests', 'the', 'and', 'with', 'rows', 'test', 'file', 'this', 'that', 'return',
                      'returns', 'uses', 'when', 'into', 'from', 'default', 'update', 'adds', 'keeps', 'after',
                      'before', 'header', 'sorts', 'keeps', 'counts'}]
        if tokens and not any(token in content for token in tokens):
            stale += 1
            stale_bytes += len(text.encode())

    match = glob.glob(str(SESSIONS / '*' / f'session-{session.split("session-")[1]}' / 'session.v4.jsonl.zstd'))
    events = []
    if match:
        with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(open(match[0], 'rb').read())) as reader:
            events = [json.loads(line) for line in reader.read().decode().splitlines() if line.strip()]
    texts = [''.join(block.get('text', '') for block in event['data']['summary'] if block.get('type') == 'text')
             for event in events if event.get('type') == 'compaction/summary']
    latest = re.search(r'^Latest request: "(.*)"$', texts[-1], re.M) if texts else None
    quotes = re.findall(r'^\d+\. "([\s\S]*?)"$', texts[-1], re.M) if texts else []
    latest_dup = len(latest.group(0).encode()) if latest and quotes and quotes[-1].strip() == latest.group(1).strip() else 0
    index_total = sum(len(re.search(r'^Evidence index.*$', text, re.M).group(0).encode())
                      for text in texts if re.search(r'^Evidence index.*$', text, re.M))
    print(f"{directory.name}: active={len(active)} "
          f"V6 dup={dup}/{len(adds)} {dup_bytes}/{add_bytes}B ({100 * dup_bytes / max(1, add_bytes):.0f}%) | "
          f"V5 stale={stale}/{checked} {stale_bytes}B | latestDup={latest_dup}B | indexTotal={index_total}B/{len(texts)}cp")
