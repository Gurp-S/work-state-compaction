"""Read-only default/override capability audit; no turns or config writes."""
from pathlib import Path
import json
import math
import sys
import time
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash
from native_owned_process import OwnedNativeRPC
from native_host_controls import settings

PARENT = Path('D:/agent-task-runs/native-compaction-feasibility-20261026-v1')
OUT = Path('D:/agent-task-runs/native-compaction-feasibility-20261026-v2')
OUT.mkdir(exist_ok=False)
WORK = OUT / 'workspace'
WORK.mkdir()
source = Path('D:/agent-task-runs/wsc-a3-dev-C-calibrated-20261026-v1')
registered = read(source / 'registration.json')['session']
# This is a config-read probe, not the browser/application host. Do not carry
# another workspace's private browser-cache path into this new directory.
reg = {key: registered[key] for key in ('executable', 'executable_sha256', 'model', 'effort', 'host_feature_overrides')}
reg['workspace'] = str(WORK)
assert file_hash(reg['executable']) == reg['executable_sha256']
parent_digest = file_hash(PARENT / 'next-admission-envelope.json')
phase_digest = file_hash(source / 'phase-journal.json')
fields = ('model_auto_compact_token_limit', 'model_auto_compact_token_limit_scope', 'model_context_window', 'compact_prompt')
result = dict(model_calls=0, config_written=False, native_B_changed=False, records=[],
    runtime_compaction_proven=False, benefit_proven=False,
    documentation='https://learn.chatgpt.com/docs/config-file/config-reference')
begin = time.monotonic()
for name, extra in [('default', []), ('isolated_override', ['model_auto_compact_token_limit=96000'])]:
    server = None
    record = dict(name=name, startup_override=extra)
    try:
        # Preserve the session's established model/effort/feature settings.
        server = OwnedNativeRPC(reg['executable'], cwd=WORK, stderr_path=OUT / (name + '-stderr.txt'),
            settings=settings(reg) + extra)
        server.call('initialize', dict(clientInfo=dict(name='compaction_read_audit', version='1'), capabilities=dict(experimentalApi=True)))
        server.send(dict(method='initialized'))
        observed = server.call('config/read', dict(cwd=str(WORK), includeLayers=False))
        config = observed['config']
        # Never persist other configuration fields or credentials.
        record['config_projection'] = {key: config.get(key) for key in fields if key != 'compact_prompt'}
        record['compaction_prompt_override_present'] = bool(config.get('compact_prompt'))
        record['origin_projection'] = {key: observed.get('origins', {}).get(key) for key in fields if key != 'compact_prompt'}
    except Exception as exc:
        record['error'] = type(exc).__name__ + ':' + str(exc)
    finally:
        record['cleanup'] = server.close() if server else dict(empty_confirmed=True, process_started=False)
    result['records'].append(record)
phase = read(source / 'phase-journal.json')
receipts = phase['receipts']['response_receipts']
vectors = [entry['usage'] for entry in receipts]
total_input = sum(v['input_tokens'] for v in vectors)
cached = sum(v['cached_input_tokens'] for v in vectors)
result['historical_usage'] = dict(responses=len(vectors), input_tokens=total_input, cached_input_tokens=cached,
    uncached_input_tokens=total_input-cached, cached_input_fraction=cached/total_input,
    output_tokens=sum(v['output_tokens'] for v in vectors),
    first_input=vectors[0]['input_tokens'], last_input=vectors[-1]['input_tokens'],
    stage_usage_complete=phase['usage_complete'], source_sha256=phase_digest)
result['counter_threshold_observations'] = [dict(threshold=threshold,
    first_reported_response_at_or_above=next((i for i, v in enumerate(vectors, 1) if v['total_tokens'] >= threshold), None),
    reported_responses_at_or_above=sum(v['total_tokens'] >= threshold for v in vectors))
    for threshold in (64000, 96000, 128000)]
result['threshold_scope'] = 'Historical reported per-response counters only; not a simulated continuation, exact live trigger or savings estimate'
result['elapsed_seconds'] = time.monotonic() - begin
assert file_hash(PARENT / 'next-admission-envelope.json') == parent_digest
assert file_hash(source / 'phase-journal.json') == phase_digest
result['parent_envelope_sha256'] = parent_digest
save(OUT / 'audit.json', result)
parent = read(PARENT / 'next-admission-envelope.json')
save(OUT / 'next-admission-envelope.json', {**parent,
    'remaining_limits': {**parent['remaining_limits'],
        'max_seconds': parent['remaining_limits']['max_seconds'] - math.ceil(result['elapsed_seconds'])},
    'parent_envelope_sha256': parent_digest, 'capability_audit_model_calls': 0})
print(json.dumps(result, ensure_ascii=False))
