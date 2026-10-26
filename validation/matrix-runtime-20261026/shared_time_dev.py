"""User-approved time allocation change; all other C admission conditions retained."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import save, read
from prepare_dev_trial import prepare
from run_dev_trial import execute

OUT = Path('D:/agent-task-runs/wsc-a3-dev-C-sharedtime-20261026-v1')
PRIOR = Path('D:/agent-task-runs/wsc-a3-dev-C-20261026-v1')

if sys.argv[1] == 'prepare':
    assert read(PRIOR / 'result.json')['cleanup']['empty_confirmed']
    prepare(OUT=OUT, runtime_workspace=PRIOR / 'workspace')
    save(OUT / 'policy-adoption.json', dict(user_choice='采用共享剩余时间（推荐）',
        source_proposal=str(PRIOR / 'proposed-shared-time.json'),
        ordinary_time_seconds=2700, arm_time_seconds=2700, arm_tokens=6000000, arm_responses=120,
        old_failed_ledger_resumed=False, historical_unknowns_preserved=True))
elif sys.argv[1] == 'run':
    assert read(OUT / 'policy-adoption.json')['ordinary_time_seconds'] == 2700
    execute(OUT=OUT, ordinary_time_shared=True, budget_parent=PRIOR)
else:
    raise ValueError('unknown_action')
