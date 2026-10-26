"""Retained native B/C execution for one preregistered two-boundary task."""
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sys
import time

from native_evidence import read,save,manifest,digest,file_hash
from native_continuity_checks import archive_workspace,aggregate
from native_group_admission import NativeGroupAdmission
from native_pair_admission import observe
from native_pair_workspace import preserve_arm
from native_runtime_probe import verify_runtime
from native_thread_archive import archive_threads
from native_task_checks import grade,require
from native_host_checkpoint import PendingHostCheckpoint
from native_successor_checkpoint import host_origin,PendingSuccessorCheckpoint
from run_native_pair import NativeRPC,SETTINGS,initialize,import_items,phase,verify_pins,audit_host
from run_control_continuation import open_thread,require_completed,prior_fact
from run_native_continuity import execution_item
from strict_jsonl_study import STAGES,prepare
from wsc.contracts import encode


def run(area):
    area=Path(area).resolve();reg=read(area/'registration.json')
    seal=read(area/'prepared.json')
    require(file_hash(area/'registration.json')==seal['registration_sha256'] and
            file_hash(area/'baseline/receipt.json')==seal['baseline_sha256'],'preparation_changed')
    verify_pins(reg)
    require(reg['stages']==STAGES and manifest(reg['workspace'])==reg['initial_manifest'],'initial_source_changed')
    save(area/'started.json',{'utc':datetime.now(timezone.utc).isoformat(),'retry':False})
    opened,phases,entries={},{},[]
    result={'status':'started','stages':entries,'cash':None,'goal_complete':False}
    current=reg['initial_manifest'];prior=None
    try:
        with NativeRPC(reg['executable'],cwd=reg['workspace'],stderr_path=area/'stderr.txt',settings=SETTINGS) as server:
            initialize(server)
            runtime=verify_runtime(server,reg['workspace'],reg['runtime_command'],area/'runtime-preflight')
            plugins=server.call('plugin/list',{'cwds':[reg['workspace']],'forceRefetch':False},timeout=45)
            skills=server.call('skills/list',{'cwds':[reg['workspace']],'forceReload':False},timeout=45)
            save(area/'discovery.json',{'plugins':plugins,'skills':skills})
            require(not plugins.get('marketplaceLoadErrors'),'plugin_discovery_failed')
            def fact_for(stage):
                fact=execution_item(reg['workspace'],stage,current,prior)
                fact['content'][0]['text']=encode({**json.loads(fact['content'][0]['text']),'task_runtime':runtime})
                return fact
            initial_fact=fact_for(STAGES[0]);controls=[initial_fact]
            require(reg['admission_warmup_threads']==1,'warmup_policy_changed')
            for name in ('warmup','B','C1','C2'):
                cell=area/'initial'/name;cell.mkdir(parents=True)
                opened[name]=open_thread(server,reg,cell)
                import_items(server,opened[name],controls,cell)
                admission=observe(opened[name],controls);save(cell/'admission.json',admission)
                require(admission['response_count']==0,'unregistered_initial_inference')
            observations=lambda:{n:observe(opened[n],controls) for n in ('B','C1','C2')}
            gate=NativeGroupAdmission(observations(),members={'B','C1','C2'})
            save(area/'paired-admission.json',{'observations':observations(),'model_calls':0,
                 'process_id':server.proc.pid,'prompt_overrides':False,'plugin_configuration_changes':False})

            def execute(label,value,stage,*,initial=False,checkpoint=None,compact=False):
                nonlocal current,prior
                verify_pins(reg)
                require(manifest(reg['workspace'])==current,'interstage_workspace_changed')
                cell=area/label;cell.mkdir(parents=True)
                before=archive_workspace(reg['workspace'],cell/'before.zip')
                fact=initial_fact if initial else fact_for(stage)
                if initial:
                    save(cell/'admission.json',read(area/'initial/B/admission.json'))
                    save(cell/'thread-start.json',opened['B'])
                elif checkpoint:
                    checkpoint.import_into(server,value,cell,fact)
                else:
                    import_items(server,value,[fact],cell)
                fresh=initial or checkpoint is not None
                preg={**reg,'execution_fact':fact,'shared_request':stage['message'],
                      'accounting_scope':'fresh_single_turn' if fresh else 'append_only_turn',
                      'phase_budget':stage['budget']}
                save(cell/'registration.json',preg)
                outcome=phase(server,value,preg,cell,None,time.monotonic()+stage['budget']['max_seconds'],compact=compact)
                phases[label]=outcome
                after=archive_workspace(reg['workspace'],cell/'after.zip')
                entry={'label':label,'before':before,'after':after};entries.append(entry)
                require_completed(outcome)
                require(compact or len(outcome['finals'])==1,'task_final_missing')
                audit_host(cell)
                require(all(after['manifest'].get(p)==reg['initial_manifest'][p] for p in reg['protected_paths']),
                        'protected_file_changed')
                current=after['manifest']
                receipt=None
                if stage['methods']:
                    receipt=grade(reg['workspace'],reg['grader'],stage['methods'],cell/'acceptance')
                    prior=prior_fact(receipt,cell/'acceptance/receipt.json');entry['acceptance']=prior
                    require(receipt['passed'],'stage_acceptance_failed')
                else:
                    require(current==before['manifest'],'nonediting_stage_changed_workspace')
                save(cell/'stage-result.json',entry)
                return outcome,receipt

            source,source_receipt=gate.execute('B',observations(),
                lambda:execute('source_task',opened['B'],STAGES[0],initial=True))
            source_manifest=current.copy()
            source_prior=prior.copy()
            shutil.copytree(reg['workspace'],area/'source-frozen',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            require(manifest(area/'source-frozen')==source_manifest,'source_freeze_changed')
            pending=PendingHostCheckpoint(area/'C/checkpoint1',reg['workspace'],area/'source_task/rollout.jsonl',
                source,source_receipt,area/'source_task/acceptance/receipt.json',area/'source_task')
            first,first_receipt=gate.execute('C1',observations(),
                lambda:execute('C/finite_task',opened['C1'],STAGES[1],checkpoint=pending))
            origin_cell=area/'C/finite_task/host-observation'
            origin=host_origin(origin_cell/'rollout.jsonl',read(origin_cell/'admission.json'),read(origin_cell/'imported-items.json'))
            successor=PendingSuccessorCheckpoint(area/'C/checkpoint2',reg['workspace'],area/'C/finite_task/rollout.jsonl',
                first,first_receipt,area/'C/finite_task/acceptance/receipt.json',origin=origin,
                parent_path=area/'C/checkpoint1/package.json',
                parent_digest=read(area/'C/finite_task/host-publication.json')['package_digest'])
            gate.execute('C2',observations(),
                lambda:execute('C/line_budget_task',opened['C2'],STAGES[2],checkpoint=successor))
            execute('C/handoff',opened['C2'],STAGES[3])
            review_paths=[area/label/'phase-outcome.json' for label in phases if label.startswith('C/')]
            review_paths += [area/'C/finite_task/acceptance/receipt.json',area/'C/line_budget_task/acceptance/receipt.json']
            review_request={'current_manifest_sha256':digest(current),'evidence_sha256':{str(p):file_hash(p) for p in review_paths}}
            save(area/'C/review-request.json',review_request)
            print(json.dumps({'status':'C_semantic_review_pending','path':str(area/'C/review-request.json')}),flush=True)
            review_path=area/'C/review.json';stop=time.monotonic()+reg['review_wait_seconds']
            while not review_path.exists() and time.monotonic()<stop:
                time.sleep(1)
            require(review_path.exists(),'C_review_not_received')
            review=read(review_path)
            require(review.get('status')=='qualified_for_registered_task' and review.get('binding')==review_request,
                    'C_semantic_review_failed')
            require(all(file_hash(p)==h for p,h in review_request['evidence_sha256'].items()),'C_review_evidence_changed')
            require(manifest(reg['workspace'])==current,'C_workspace_changed_during_review')
            preserve_arm(area,'C',area/'source-frozen',source_manifest,restore_initial=True)
            current=source_manifest;prior=source_prior
            for index,stage in enumerate(STAGES[1:3],1):
                compact={**stage,'methods':None,'message':stage['message'],'budget':reg['compaction_budget']}
                execute(f'B/compaction{index}',opened['B'],compact,compact=True)
                execute('B/'+stage['id'],opened['B'],stage)
            execute('B/handoff',opened['B'],STAGES[3])
            preserve_arm(area,'B',area/'source-frozen',source_manifest,restore_initial=False)
            result['status']='B_and_C_executed_final_review_pending'
    except Exception as exc:
        result.update(status='stopped',error=type(exc).__name__+':'+str(exc))
    finally:
        result['threads']=archive_threads(area,opened)
        try:
            verify_pins(reg)
            result['usage']=aggregate(list(phases.values()))
            result['C_usage']=aggregate([p for n,p in phases.items() if n.startswith('C/')])
            result['B_usage']=aggregate([p for n,p in phases.items() if n.startswith('B/')])
            result['source_usage']=aggregate([p for n,p in phases.items() if n=='source_task'])
            require(all('accounting_error' not in value for value in result['threads'].values()),'archive_missing_or_incomplete')
            archived=[r for value in result['threads'].values() for r in value['receipts']['response_receipts']]
            actual=[r for value in phases.values() for r in value.get('receipts',{}).get('response_receipts',[])]
            require(len(archived)==len({r['response_id'] for r in archived}),'duplicate_archive_response')
            require({r['response_id']:r['usage'] for r in archived}=={r['response_id']:r['usage'] for r in actual},
                    'unaccounted_archived_response')
            result['archive_usage_verified']=True
        except Exception as exc:
            result.update(status='stopped',accounting_error=type(exc).__name__+':'+str(exc))
        save(area/'result.json',result)
        print(json.dumps({k:v for k,v in result.items() if k not in {'threads','stages'}},ensure_ascii=False),flush=True)


if __name__=='__main__':
    {'prepare':prepare,'run':run}[sys.argv[1]](Path(sys.argv[2]))
