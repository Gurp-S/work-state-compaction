"""Replay the failed bootstrap gate, then inspect four zero-inference starts."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, state, digest, file_hash
from native_host_controls import bootstrap_items, settings, FEATURE_OVERRIDES
from native_owned_process import OwnedNativeRPC
from native_rollout_snapshot import capture_rollout

AREA = Path(sys.argv[1])
OLD = Path('D:/agent-task-runs/wsc-application-matrix-20261025-v2')


def probe(index):
    root = AREA / str(index)
    root.mkdir()
    work = root / 'workspace'
    work.mkdir()
    reg = read(OLD / 'registration.json')['conditions']
    overrides = dict(effort=reg['effort'], host_feature_overrides=FEATURE_OVERRIDES)
    server = OwnedNativeRPC(reg['executable']['path'], cwd=work,
                            stderr_path=root/'stderr.txt', settings=settings(overrides))
    try:
        save(root/'initialize.json', server.call('initialize', dict(
            clientInfo=dict(name='wsc_application_study',version='1'),capabilities=dict(experimentalApi=True))))
        server.send(dict(method='initialized'))
        opened = server.call('thread/start', dict(cwd=str(work), model=reg['model'],
            allowProviderModelFallback=False, approvalPolicy='never', sandbox='workspace-write',
            runtimeWorkspaceRoots=[str(work)], ephemeral=False, dynamicTools=[]), timeout=30)
        save(root/'thread-start.json',opened)
        server.call('thread/inject_items',dict(threadId=opened['thread']['id'],items=[
            dict(type='message',role='developer',content=[dict(type='input_text',text='{"kind":"host_control_observation"}')])]))
        path = Path(opened['thread']['path'])
        deadline = time.monotonic()+5
        while not path.exists() and time.monotonic()<deadline:
            time.sleep(.05)
    finally:
        cleanup = server.close()
        save(root/'cleanup.json', cleanup)
    snap = capture_rollout(path,archive=root/'closed.jsonl')
    assert snap.metadata['parse_complete']
    assert not any(row['type']=='token_usage_record' for row in snap.rows)
    normalized = bootstrap_items(state(snap.rows),work)
    save(root/'normalized.json',normalized)
    return dict(index=index, bootstrap_sha256=digest(normalized), cleanup=cleanup, model_calls=0)


def main():
    AREA.mkdir(exist_ok=False)
    pair = OLD / 'admission/collaboration_r1'
    observations = [read(pair/(arm+'-0.json'))['observation'] for arm in ('B','C')]
    a,b = [x['bootstrap_items'] for x in observations]
    a,b = [bootstrap_items(x,'D:/unused-workspace') for x in (a,b)]
    assert a != b, 'real_tool_difference_was_hidden'
    same = deepcopy(a)
    same[0]['id']='new-transport-id'
    assert bootstrap_items(same,'D:/unused-workspace') == a
    mutated = deepcopy(a)
    mutated[0]['tools'][0]['tools'][0]['description'] += '\nchanged'
    assert bootstrap_items(mutated,'D:/unused-workspace') != a
    with ThreadPoolExecutor(max_workers=4) as pool:
        starts=list(pool.map(probe,range(4)))
    result=dict(starts=starts, all_equal=len({x['bootstrap_sha256'] for x in starts})==1,
        replay=dict(real_tool_difference_rejected=True, transport_id_ignored=True, description_change_rejected=True),
        settings=settings(dict(effort='max',host_feature_overrides=FEATURE_OVERRIDES)),
        implementation_sha256=file_hash(ROOT/'experiments/native_host_controls.py'), model_calls=0)
    save(AREA/'result.json',result)
    print(result)
    assert result['all_equal']


if __name__=='__main__':
    main()
