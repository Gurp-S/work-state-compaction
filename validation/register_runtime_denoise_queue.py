"""Add one dependent arm without dispatching or reallocating experiment funds."""
from hashlib import sha256
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parent
DEST=ROOT/'reviews/acceptance-matrix-admission-20261028/runtime-denoise-additional-arm-queue.json'


def digest(path):
    value=sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):value.update(block)
    return value.hexdigest()


def main():
    roots=[Path('D:/agent-task-runs/wsc-matrix-runtime-followup-20261029-v1'),
        Path('D:/agent-task-runs/wsc-matrix-two-repetitions-20261029-v1')]
    results=[]
    for folder in roots:
        closed=json.loads((folder/'closure.json').read_text(encoding='utf-8'))
        if closed['budget']['status']!='closed':raise ValueError('prior_results_not_closed')
        results.append(dict(root=str(folder),registration_sha256=digest(folder/'registration.json'),
            closure_sha256=digest(folder/'closure.json'),ledger_sha256=digest(folder/'coordinator-private/ledger.db')))
    files=list((ROOT/'src/wsc/denoise').glob('*.py'))+[REPO/'dsh-wsc/engine.js',REPO/'dsh-wsc/lib/denoise.js',
        REPO/'python/tools/bash_tool/output_view.py',REPO/'python/tools/bash_tool/terminal_ops.py',
        ROOT/'reviews/runtime-denoise-additional-arm-plan.md']
    schema=Path('D:/agent-task-runs/wsc-runtime-denoise-admission-20261029-v1/schema')
    protocol=[schema/'ClientRequest.json',schema/'DynamicToolCallResponse.json',
        schema/'v2/TurnStartParams.json',schema/'v2/HooksListResponse.json',schema/'v2/HookCompletedNotification.json']
    executable=Path('C:/Users/48522/AppData/Local/OpenAI/Codex/bin/08d187884f2330d1/codex.exe')
    value=dict(status='queued_after_current_projection_continuation_results',additive_only=True,
        rerun_previous_valid_arms=False,new_model_calls=0,new_budget_allocated=False,dispatch_admitted=False,
        dependencies=dict(current_three_Bprime_C_pairs='complete',hot_projection_zero_model_qualification='complete',
            old_new_projection_model_continuation='pending',native_runtime_result_transform_and_raw_recovery='unqualified'),
        new_arm=dict(name='C_parent_plus_runtime_denoise',parent='Freeze qualified C configuration after pending continuation results, before denoise outcomes.',
            intended_only_difference='Runtime tool-result denoise flag',planned_repetitions=3,max_parallel=2,
            proposed_per_run_limits=dict(max_total_tokens=500000,max_responses=14,max_seconds=800),budget_claim=None),
        reusable_results=results,implementation_sha256={str(p):digest(p) for p in files},
        protocol_sha256={str(p):digest(p) for p in protocol},executable_sha256=digest(executable),
        acceptance=dict(code_checks=11,structured_assertions=5,no_extra_LLM_judge=True,
            constraints_may_not_increase=True,raw_receipts_and_call_identity_unchanged=True,
            full_raw_recovery_required=True,unknown_or_error_or_read_bypass=True),
        limitations=['Existing 50 percent number is synthetic bytes, not model tokens or task success.',
            'Current native transport does not implement an ordinary-command result transform.',
            'Current CLI exposes hook metadata; replacement semantics and timing still need qualification.',
            'Changing harness or tools can invalidate strict reuse; retain old results and scope comparison explicitly.',
            'Historical replay is not a live runtime experiment.'])
    with DEST.open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
    receipt=Path('D:/agent-task-runs/wsc-runtime-denoise-admission-20261029-v1/investigation.json')
    receipt.write_text(json.dumps(dict(new_model_calls=0,queue=str(DEST),queue_sha256=digest(DEST),
        executable_sha256=value['executable_sha256'],protocol_sha256=value['protocol_sha256']),indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status=value['status'],rerun_previous_valid_arms=False,new_model_calls=0,new_budget_allocated=False)))


if __name__=='__main__':main()
