"""Sidecar diagnostic: exact archived sources, narrower control and center checks."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import os
import subprocess
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,file_hash,manifest,digest
from native_owned_process import ProcessOwner
COHORT=Path('D:/agent-task-runs/wsc-a3-fixed-S2-repeated-BC-20261026-v1')
OUT=Path('D:/agent-task-runs/wsc-scope-locator-review-20261027-v1')
OUT.mkdir(exist_ok=False)
FROZEN=Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1/staged/frozen-workspace')
reg=read(COHORT/'registration.json')['sessions']['C']
original=Path(__file__).with_name('s3-scope-check.mjs')
text=original.read_text(encoding='utf-8')
old="page.getByRole('button', {name: /atlas-pro/}).or(page.getByRole('checkbox', {name: /atlas-pro/}))"
new="page.locator('.xy-a3-filters').getByRole('button', {name: /atlas-pro/}).or(page.locator('.xy-a3-filters').getByRole('checkbox', {name: /atlas-pro/}))"
assert text.count(old)==1
text=text.replace(old,new)
anchor="  await page.goto(host.origin);"
assert text.count(anchor)==1
text=text.replace(anchor,"  const center = name => chart(name).locator('.pointer-events-none.absolute.inset-0 > span').first();\n"+anchor)
for name in ('成本 · 模型','请求 · 模型','整体命中率','输入 token · 构成'):
    text=text.replace("expect(chart('"+name+"'))","expect(center('"+name+"'))")
checker=OUT/'scoped-control-and-center-check.mjs'
checker.write_text(text,encoding='utf-8')
cases=[('qualified_C',COHORT/'preserved-before-C',Path('D:/agent-task-runs/wsc-a3-dev-C-auto-compaction-20261026-v1/S3-scope/result.json')),
    ('R01_B',COHORT/'execution-v2/R01/preserved-final-B',COHORT/'execution-v2/R01/B/S3-scope/result.json'),
    ('R01_C',COHORT/'execution-v2/R01/preserved-final-C',COHORT/'execution-v2/R01/C/S3-scope/result.json')]
for name,snapshot,old_result in cases:
    gui=OUT/name/'gui';gui.mkdir(parents=True)
    before=read(snapshot/'before-manifest.json')
    with zipfile.ZipFile(snapshot/'changed-source.zip') as archive:
        for key,expected in before.items():
            if not (key.startswith('gui/src/') or Path(key).parent==Path('gui')):continue
            if key in archive.namelist():data=archive.read(key)
            elif (FROZEN/key).is_file():data=(FROZEN/key).read_bytes()
            else:data=(snapshot/'retained-extra'/key).read_bytes()
            assert sha256(data).hexdigest()==expected
            target=OUT/name/key;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    observed=manifest(gui/'src')
    assert observed=={key.removeprefix('gui/src/'):value for key,value in before.items() if key.startswith('gui/src/')}
    # A directory junction shares only dependencies. Source and all outputs are
    # physically separate, and all case source bytes were verified above.
    command="New-Item -ItemType Junction -Path '"+str(gui/'node_modules')+"' -Target '"+str(Path(reg['workspace'])/'gui/node_modules')+"' | Out-Null"
    subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',command],check=True,
        capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    save(OUT/name/'source-binding.json',dict(gui_sha256=digest(observed),source_files=observed,
        archived_snapshot=str(snapshot),original_result_sha256=file_hash(old_result)))
save(OUT/'registration.json',dict(model_calls=0,original_checker_sha256=file_hash(original),variant_sha256=file_hash(checker),
    changes=['Only model-filter-bar control locator','Chart center values instead of all chart text'],
    semantic_checks_unchanged=['selected totals','date reset','keyboard selection'],
    old_results_unchanged=True,original_official_contract_changed=False))
def run(case):
    name,snapshot,old_result=case
    owner=ProcessOwner();proc=None
    folder=OUT/name
    outcome=dict(name=name)
    try:
        with (folder/'stdout.txt').open('x',encoding='utf-8') as stdout,(folder/'stderr.txt').open('x',encoding='utf-8') as stderr:
            proc=subprocess.Popen([reg['node_executable'],str(checker),str(folder/'gui'),reg['fixture_root'],str(folder/'probe')],
                env={**os.environ,'PLAYWRIGHT_BROWSERS_PATH':reg['browser_cache']},stdout=stdout,stderr=stderr,
                creationflags=subprocess.CREATE_NO_WINDOW)
            owner.attach(proc);outcome['exit_code']=proc.wait(timeout=90)
    finally:
        outcome['cleanup']=owner.close()
        if proc:proc.wait(timeout=5)
    result=read(folder/'probe/result.json')
    assert manifest(folder/'gui/src')==read(folder/'source-binding.json')['source_files']
    outcome.update(old_passed=read(old_result)['passed'],new_passed=result['passed'],checks=result['checks'],source_unchanged=True)
    save(folder/'comparison.json',outcome)
    return outcome
with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(run,cases))
assert results[0]['new_passed'] and not results[1]['new_passed'],'positive/negative scope control changed'
save(OUT/'result.json',dict(results=results,model_calls=0,original_official_contract_changed=False))
print([dict(name=r['name'],old_passed=r['old_passed'],new_passed=r['new_passed'],checks=[(c['id'],c['passed']) for c in r['checks']]) for r in results])
