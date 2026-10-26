"""Zero-model A/B: original identical component tests on S2 and final C source."""
from pathlib import Path
import sys,shutil,subprocess,json,concurrent.futures
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import save,read,manifest,file_hash
AREA=Path('D:/agent-task-runs/wsc-a3-dev-C-incremental-20261026-v1')
FROZEN=Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1/staged/frozen-workspace/gui')
CURRENT=Path('D:/agent-task-runs/wsc-a3-select-scoped-20261026-v1/workspace/gui')
OUT=AREA/'component-source-ab';OUT.mkdir(exist_ok=False)
tests=['src/components/A3NativePanel.test.tsx','src/components/A3SnapshotPanel.test.tsx']
initial=manifest(CURRENT/'src')
def run(label):
    dest=OUT/label/'gui';shutil.copytree(FROZEN,dest)
    if label=='candidate':
        shutil.copytree(CURRENT/'src',dest/'src',dirs_exist_ok=True)
        for name in tests:shutil.copyfile(FROZEN/name,dest/name)
    assert all(file_hash(dest/name)==file_hash(FROZEN/name) for name in tests)
    link=dest/'node_modules'
    assert not link.exists() and dest.resolve().is_relative_to(OUT.resolve())
    subprocess.run(['powershell.exe','-NoProfile','-Command',f"New-Item -ItemType Junction -Path '{link}' -Target '{CURRENT/'node_modules'}' | Out-Null"],check=True,capture_output=True)
    report=OUT/label/'vitest.json'
    command=['E:/nodejs/node.exe',str(dest/'node_modules/vitest/vitest.mjs'),'run',*tests,'--reporter=json',f'--outputFile={report}']
    result=subprocess.run(command,cwd=dest,encoding='utf-8',errors='strict',capture_output=True,timeout=90)
    (OUT/label/'stdout.txt').open('x',encoding='utf-8').write(result.stdout)
    (OUT/label/'stderr.txt').open('x',encoding='utf-8').write(result.stderr)
    data=read(report)
    failures=[]
    for suite in data['testResults']:
        for case in suite.get('assertionResults',[]):
            if case['status']=='failed':failures.append(case['fullName'])
    return dict(label=label,exit_code=result.returncode,tests=data['numTotalTests'],passed=data['numPassedTests'],
        failed=data['numFailedTests'],failure_names=failures,original_test_hashes={name:file_hash(dest/name) for name in tests},
        source_manifest=manifest(dest/'src'),dependencies='Shared directory junction to the same closed private runtime')
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,['baseline','candidate']))
assert manifest(CURRENT/'src')==initial
before,after=results
review=dict(results=results,source_unchanged=True,model_calls=0,identical_original_tests=True,
    introduced_failure_names=sorted(set(after['failure_names'])-set(before['failure_names'])),
    resolved_failure_names=sorted(set(before['failure_names'])-set(after['failure_names'])),
    persistent_failure_names=sorted(set(before['failure_names'])&set(after['failure_names'])),
    scope='Original component tests only; no claim that all failures are test defects or full project regression')
save(OUT/'result.json',review)
print(json.dumps({k:v for k,v in review.items() if k!='results'},ensure_ascii=False))
print(json.dumps([dict(label=r['label'],tests=r['tests'],passed=r['passed'],failed=r['failed']) for r in results]))
