"""Public-tool timeline and actual input measurements; no model reasoning inspection."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save

OUT = Path('D:/agent-task-runs/wsc-a3-dev-C-20261026-v1')
COMMON = Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')
phase = read(OUT / 'phase-journal.json')
rows = [json.loads(line) for line in (OUT / 'closed-native.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
rows = rows[phase['turn_accounting']['before']['records']:]
start = (OUT / 'grant.json').stat().st_mtime
expected = set(read(COMMON / 'registration.json')['expected_checks']['a3']['3'])
final_source = read(OUT / 'S3-acceptance/registration.json')['source_manifest']
calls, observations, commands = {}, [], []
for row in rows:
    value = row.get('payload', {})
    if row['type'] != 'response_item': continue
    elapsed = round(datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00')).timestamp() - start, 3)
    if value.get('type') == 'custom_tool_call':
        raw = value.get('input', '')
        found = re.search(r'\bcmd\s*:\s*("(?:[^"\\]|\\.)*")', raw)
        command = json.loads(found[1]) if found else None
        category = ('patch' if 'tools.apply_patch' in raw else
            'official_browser_check' if command and 'run-acceptance.mjs' in command and ('& ' in command or 'node ' in command) else
            'typecheck' if command and ('tsc.cmd' in command or 'npm run typecheck' in command) else
            'supplemental_browser_check' if command and 'controlled-refresh' in command and '& ' in command else
            'source_or_artifact_read' if command and any(key in command for key in ('Get-Content', 'rg ', 'Test-Path')) else
            'other_or_unparsed')
        item = dict(call_id=value['call_id'], seconds_after_grant=elapsed, category=category, command=command)
        calls[value['call_id']] = item; commands.append(item)
    elif value.get('type') == 'custom_tool_call_output':
        output = value.get('output')
        text = '\n'.join(block.get('text', '') for block in output if isinstance(block, dict)) if isinstance(output, list) else str(output)
        observed = []
        for line in text.splitlines():
            try: parsed = json.loads(line)
            except (ValueError, TypeError): continue
            if isinstance(parsed, dict) and parsed.get('id') in expected and type(parsed.get('passed')) is bool:
                observed.append(dict(id=parsed['id'], passed=parsed['passed']))
        if {item['id'] for item in observed if item['passed']} == expected:
            command = calls.get(value['call_id'], {}).get('command') or ''
            target = re.search(r"Join-Path\s+\$root\s+'(validation[^']+)'", command)
            receipt = OUT / 'workspace' / target[1].replace('\\', '/') / 'registration.json' if target else None
            matching = read(receipt)['source_manifest'] == final_source if receipt and receipt.exists() else None
            observations.append(dict(seconds_after_grant=elapsed, passed_checks=11,
                registration=str(receipt) if receipt else None, matches_final_independent_source=matching))
values = []
for name, path in [('B-historical', COMMON / 'arms/B/output/S3-phase/phase-outcome.json'),
    ('C-prior', Path('D:/agent-task-runs/wsc-a3-c-continuation-20261026-v1/phase-journal.json')),
    ('C-current', OUT / 'phase-journal.json')]:
    item = read(path); r = item['receipts']['response_receipts']
    values.append(dict(label=name, first_input_tokens=r[0]['usage']['input_tokens'],
        last_input_tokens=r[-1]['usage']['input_tokens'], known_responses=len(r)))
result = dict(command_classification=dict(Counter(item['category'] for item in commands)),
    commands=commands, completed_public_cumulative_checks=observations, input_measurements=values,
    copied_solution_path_mentions=sum('wsc-a3-common-prefix-20261025-v1' in (item['command'] or '') for item in commands),
    model_calls=0, scope='Observed public actions only; classifications are syntactic and not causal attribution. Historical B is not a matched current arm.')
save(OUT / 'public-timeline-audit.json', result)
print({key: result[key] for key in ('command_classification', 'completed_public_cumulative_checks', 'input_measurements')})
