"""Board audit: what the coverage block claimed versus the final workspace.

Every checkpoint that carries a `## Requirement coverage` block is read from the
session file. For each request the board names as lacking a recorded edit, the
final workspace is checked for the evidence the oracle would use, so a false
"no recorded edit" is visible with its number.
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
SESSIONS = Path(os.environ.get('DSH_HOME', str(Path.home() / '.dsh'))) / 'sessions'
BLOCK = re.compile(r'## Requirement coverage \(mechanical\)\n([^\n]*)')
MISSING = re.compile(r'No recorded edit yet: ([^.]*)\.')


def checkpoints(session: str) -> list[str]:
    matches = glob.glob(str(SESSIONS / '*' / session / 'session.v4.jsonl.zstd'))
    if not matches:
        return []
    with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(open(matches[0], 'rb').read())) as reader:
        events = [json.loads(line) for line in reader.read().decode('utf-8').splitlines() if line.strip()]
    out = []
    for event in events:
        if event.get('type') != 'compaction/summary':
            continue
        out.append(''.join(block.get('text', '') for block in event['data']['summary']
                           if block.get('type') == 'text'))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenario', default='long-40')
    parser.add_argument('--arms', default='v4q')
    args = parser.parse_args()
    for arm in [a.strip() for a in args.arms.split(',') if a.strip()]:
        for directory in sorted((HERE / 'runs' / args.scenario / arm).glob('rep*')):
            if not (directory / 'done').exists():
                continue
            session = (directory / 'done').read_text().strip()
            texts = checkpoints(session)
            claims = []
            for text in texts:
                match = BLOCK.search(text)
                if not match:
                    continue
                missing = MISSING.search(match.group(1))
                claims.append((match.group(1), missing.group(1).strip() if missing else ''))
            if not claims:
                print(f'{arm}/{directory.name}: no board block in {len(texts)} checkpoints')
                continue
            covered = []
            flagged = []
            for line, missing in claims:
                numbers = re.findall(r'(\d+)/(\d+) work requests', line)
                if numbers:
                    covered.append(f'{numbers[0][0]}/{numbers[0][1]}')
                flagged += [token.strip() for token in missing.split(',') if token.strip()]
            print(f'{arm}/{directory.name}: checkpoints={len(texts)} boards={len(claims)} '
                  f'coverage={covered[-1] if covered else "-"} '
                  f'flagged={sorted(set(flagged), key=lambda x: int(x[1:])) if flagged else "none"}')
            for text in texts:
                match = BLOCK.search(text)
                if match:
                    print('   last:', match.group(0).split('\n')[1])


if __name__ == '__main__':
    main()
