"""Review existing offline browser receipts without repeating any executions."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).parent
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash,manifest

runs={name:Path('D:/agent-task-runs')/folder for name,folder in {
    'initial_baseline':'wsc-a3-acceptance-20261023-v1',
    'large_date_cases':'wsc-a3-acceptance-large-20261023-v1',
    'price_fault':'wsc-a3-calibration-price-20261023-v1',
    'race_fault':'wsc-a3-calibration-race-20261023-v2',
    'final_scoped':'wsc-a3-acceptance-final-scoped-20261023-v1',
}.items()}
bound={}
current_gui=manifest(ROOT.parent/'gui/src')
for name,folder in runs.items():
    registration=read(folder/'registration.json')
    result=read(folder/'result.json')
    assert result['status']=='completed_checks' and registration['source_manifest']==current_gui
    assert not result['full_task_qualified']
    entries=[]
    for item in result['outcomes']:
        receipt=read(folder/item['receipt'])
        assert not receipt['errors'] and not receipt['forbidden']
        assert file_hash(folder/receipt['screenshot']['path'])==receipt['screenshot']['sha256']
        entries.append(dict(id=item['id'],passed=item['passed'],path=str(folder/item['receipt']),sha256=file_hash(folder/item['receipt'])))
    bound[name]=dict(result_path=str(folder/'result.json'),result_sha256=file_hash(folder/'result.json'),
        registration_sha256=file_hash(folder/'registration.json'),entries=entries)
baseline=read(runs['initial_baseline']/'result.json')
assert baseline['automated_count']==21 and baseline['automated_passes']==18
assert {e['id'] for e in baseline['outcomes'] if not e['passed']}=={'C07','C08','C10'}
assert read(runs['initial_baseline']/'C02-unpriced.json')['passed']
assert not read(runs['price_fault']/'C02-unpriced.json')['passed']
assert '¥0.00' in read(runs['price_fault']/'C02-unpriced.json')['failure']
assert read(runs['initial_baseline']/'C06.json')['passed']
race=read(runs['race_fault']/'C06.json')
assert not race['passed'] and race['old_response_status']=='delivered'
assert '2026-10-21 修复列表筛选' in race['failure']
final=read(runs['final_scoped']/'result.json')
assert {e['id'] for e in final['outcomes'] if e['passed']}=={'C06','C11'}
large=read(runs['final_scoped']/'C11.json')
assert all(ms<1000 for key,ms in large['timings'].items() if key!='bootstrap_ms')
oracle=read(OUT/'export-oracle-checks.json')
assert oracle['passed'] and oracle['accepted_examples']==4 and len(oracle['rejected_mutations'])==10
result=dict(status='scoped_A3_acceptance_calibration_reviewed',receipts=bound,
    baseline=dict(automated_checks=21,passed=18,expected_new_requirements_missing=['C07','C08','C10']),
    fault_detection=dict(unknown_cost_to_zero=True,stale_date_response=True),
    export_oracle=dict(accepted_examples=4,rejected_corruptions=10,path=str(OUT/'export-oracle-checks.json'),sha256=file_hash(OUT/'export-oracle-checks.json')),
    large_interaction_ms=large['timings'],production_gui_source_unchanged=True,new_model_calls=0,
    retained_infrastructure_failure=dict(path='D:/agent-task-runs/wsc-a3-calibration-race-20261023-v1/infrastructure-error.json',
        reason='Mutation selector expected one guard, but source has success and catch guards; corrected to remove first only.'),
    version_limits=['Initial baseline ran earlier acceptance source; C11 then gained date switching and separated bootstrap time.',
        'Final scoped run covers C06/C07/C08/C11; it is not a repeat of all 21 checks.',
        'C07/C08 remain blocked by missing new UI controls; their later happy paths are not browser-calibrated.',
        'After final execution, manual-coverage projection was corrected to include browser_and_manual C11; no browser logic changed.',
        'C11/C12/C13/C14 manual evidence remains pending; full task qualification false.'],
    complete_browser_positive_calibration=False,paid_BC_started=False,goal_complete=False)
save(OUT/'review.json',result)
print('Reviewed: baseline 18/21; 2 injected faults rejected; export oracle 4 valid/10 corrupt; production unchanged.')
