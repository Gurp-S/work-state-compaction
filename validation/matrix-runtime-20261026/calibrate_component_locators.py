"""Sidecar locator calibration: unchanged S2 app, all original tests retained."""
from pathlib import Path
import sys,shutil,subprocess,json,re
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,manifest,file_hash
OUT=Path('D:/agent-task-runs/wsc-paired-writable-admission-20261026-v1')
PAIR=Path('D:/agent-task-runs/wsc-paired-evaluation-admission-20261026-v1')
SOURCE=PAIR/'B/workspace/gui'
AREA=OUT/'component-locator-calibration';AREA.mkdir(exist_ok=False)
GUI=AREA/'gui'
FROZEN=Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1/staged/frozen-workspace/gui')
shutil.copytree(FROZEN,GUI)
subprocess.run(['powershell.exe','-NoProfile','-Command',f"New-Item -ItemType Junction -Path '{GUI/'node_modules'}' -Target '{SOURCE/'node_modules'}' | Out-Null"],check=True,capture_output=True)
tests=['src/components/A3NativePanel.test.tsx','src/components/A3SnapshotPanel.test.tsx']
changes=[]
for relative in tests:
 p=GUI/relative;original=p.read_text(encoding='utf-8');text=original
 edits=[('快照状态：','验收：')]
 if 'A3NativePanel.test' in relative:
  edits.append(("screen.getByText('账本里还没有任何一天的数据。')","screen.getByText('账本读取成功，目前没有可按日展示的数据。开始一次对话后，用量会出现在这里。')"))
 else:
  edits.extend([("screen.getByText('分模型')","screen.getByText('模型明细')"),
   ('await screen.findByText(/没读到本机用量账本（loopback only）/)','await screen.findAllByText(/没读到本机用量账本（loopback only）/)'),
   ('await screen.findByText(/本机还没有用量记录/)','await screen.findByText(\'账本尚未创建\')'),
   ('await screen.findByText(/HTTP 503/)','await screen.findAllByText(/HTTP 503/)')])
 for old,new in edits:
  count=text.count(old);assert count>0,(relative,old)
  text=text.replace(old,new);changes.append(dict(file=relative,old=old,new=new,occurrences=count))
 assert len(re.findall(r'\bexpect\(',text))==len(re.findall(r'\bexpect\(',original))
 p.write_text(text,encoding='utf-8')
original_manifest=manifest(FROZEN/'src');after=manifest(GUI/'src')
assert {k:v for k,v in original_manifest.items() if 'src/'+k not in tests}=={k:v for k,v in after.items() if 'src/'+k not in tests}
save(AREA/'registration.json',dict(original_source_manifest=original_manifest,test_variant_source_manifest=after,
 changes=changes,application_source_unchanged=True,assertion_count_preserved=True,original_tests_removed=0,
 scope='Locator-only sidecar, not a change to frozen benchmark or app'))
def run(name,pattern=None):
 command=['E:/nodejs/node.exe',str(GUI/'node_modules/vitest/vitest.mjs'),'run',*tests,'--reporter=json',f'--outputFile={AREA/name}.json']
 if pattern:command.extend(['-t',pattern])
 value=subprocess.run(command,cwd=GUI,capture_output=True,encoding='utf-8',errors='strict',timeout=90)
 (AREA/(name+'-stdout.txt')).open('x',encoding='utf-8').write(value.stdout)
 (AREA/(name+'-stderr.txt')).open('x',encoding='utf-8').write(value.stderr)
 return value.returncode,read(AREA/(name+'.json'))
code,result=run('calibrated')
summary=dict(exit_code=code,passed=result['numPassedTests'],failed=result['numFailedTests'],tests=result['numTotalTests'])
if code!=0:
 save(AREA/'result.json',dict(calibration_passed=False,summary=summary,model_calls=0,application_source_unchanged=True))
 print(summary);sys.exit(1)
assert result['numTotalTests']==36 and result['numPassedTests']==36 and result['numFailedTests']==0
baseline=read(Path('D:/agent-task-runs/wsc-a3-dev-C-incremental-20261026-v1/component-source-ab/baseline/vitest.json'))
def names(report):return sorted(c['fullName'] for s in report['testResults'] for c in s['assertionResults'])
assert names(baseline)==names(result)
# Negative control: retain all locators, make the accepted:false semantics wrong.
labels=GUI/'src/components/usage/labels.ts';original=labels.read_bytes()
try:
 text=original.decode('utf-8');old="if (accepted === false) return '待验收';";assert text.count(old)==1
 labels.write_text(text.replace(old,"if (accepted === false) return '已验收';"),encoding='utf-8')
 code,negative=run('wrong-acceptance-negative','验收判据只透传')
 assert code!=0 and negative['numFailedTests']>=1
finally:labels.write_bytes(original)
save(AREA/'result.json',dict(calibration_passed=True,baseline=dict(passed=27,failed=9),calibrated=summary,
 negative_control_failed_tests=negative['numFailedTests'],negative_control_rejected=True,
 same_test_names=True,assertion_count_preserved=True,application_source_unchanged=True,
 original_frozen_tests_unchanged=True,model_calls=0,new_failures_classified=9,
 direct_failure_classes=dict(wording_or_locator=7,nonunique_error_text=2),
 scope='Two original component suites; does not prove full project regression or WSC benefit'))
print(read(AREA/'result.json'))
