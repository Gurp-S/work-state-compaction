"""Zero-model task-runtime check through the actual unchanged native command tool."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'experiments')]
from native_linux_python import command, DIRECTORY, POLICY
from qualify_linux_native_protocol import ProbeRPC


def save(path, value):
    with path.open('x', encoding='utf-8') as stream: json.dump(value, stream, indent=2)


def linux(path):
    return '/mnt/host/'+path.drive[0].lower()+'/'+path.as_posix().split(':/',1)[1]


def checked_runtime(root):
    data = json.loads((root/'runtime-manifest.json').read_text())
    for name, expected in data['files'].items():
        h = sha256()
        with (root/name).open('rb') as f:
            for block in iter(lambda:f.read(1048576), b''): h.update(block)
        if h.hexdigest() != expected['sha256']: raise ValueError('runtime_changed:'+name)
    return sha256((root/'runtime-manifest.json').read_bytes()).hexdigest()


def main(out):
    state = subprocess.run(['wsl','--list','--verbose'], capture_output=True, timeout=10)
    if state.returncode or 'Running' in state.stdout.decode('utf-16-le') or 'Stopped' not in state.stdout.decode('utf-16-le'):
        raise ValueError('wsl_initial_state_not_owned_stopped')
    out.mkdir(parents=True, exist_ok=False)
    actor = out/'actor-root'; (actor/'actor').mkdir(parents=True); (actor/'home/.codex').mkdir(parents=True)
    runtime = Path('D:/agent-task-runs/wsc-tools/codex-0.165.0-alpha.1.2-linux-x64')
    python = runtime.parent/DIRECTORY
    pins = dict(native=checked_runtime(runtime), python=checked_runtime(python))
    secret = out/'private-canary.txt'; secret.write_text('private-runtime-canary', encoding='utf-8')
    script = '''import sys,sqlite3,json,hashlib,unittest,socket,os
class Checks(unittest.TestCase):
 def test_transaction_and_migration(self):
  db=sqlite3.connect('/work/actor/runtime.db')
  db.execute('create table task(id integer primary key, status text not null)')
  db.execute("insert into task values(1,'old')");db.commit()
  try:
   with db:
    db.execute("update task set status='new' where id=1")
    raise ValueError('rollback fixture')
  except ValueError: pass
  self.assertEqual(db.execute('select status from task').fetchone()[0],'old')
  db.execute('alter table task add column revision integer not null default 2')
  self.assertEqual(db.execute('select revision from task').fetchone()[0],2);db.close()
 def test_utf8_json_and_hash(self):
  value={'text':'状态\\r\\n🙂'};raw=json.dumps(value,ensure_ascii=False).encode()
  self.assertEqual(json.loads(raw),value)
  self.assertEqual(len(hashlib.sha256(raw).digest()),32)
  with self.assertRaises(UnicodeDecodeError): b'\\xff'.decode('utf-8')
 def test_private_and_readonly(self):
  for path in sys.argv[1:]:
   with self.assertRaises(OSError): open(path,'rb')
  with self.assertRaises(OSError): open('/opt/python/runtime-write-probe','wb')
  os.symlink(sys.argv[1],'/work/actor/private-link')
  with self.assertRaises(OSError): open('/work/actor/private-link','rb')
suite=unittest.defaultTestLoader.loadTestsFromTestCase(Checks)
r=unittest.TextTestRunner(stream=sys.stderr).run(suite)
print(json.dumps({'version':sys.version.split()[0],'tests':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'sqlite':sqlite3.sqlite_version,'uid':os.getuid(),'executable':sys.executable}))
sys.exit(0 if r.wasSuccessful() else 1)
'''
    executable=['wsl','--distribution','docker-desktop','--exec','/usr/bin/timeout','45']+command(linux(runtime),linux(actor),linux(python))+[
        '/opt/codex/bin/codex','app-server','--stdio','-c','features.multi_agent=false']
    registration=dict(command=executable, pins=pins, policy=POLICY, model_calls=0,
        source_sha256={str(p):sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),ROOT/'experiments/native_linux_python.py']},
        scope='Task Python via actual native command/exec only; no model/provider/compaction result')
    save(out/'registration.json', registration); save(out/'script.json',dict(script=script))
    rpc = None
    try:
        rpc = ProbeRPC(executable, out/'stderr.txt')
        save(out/'initialized.json', rpc.call('initialize', dict(clientInfo=dict(name='wsc_python_runtime',version='1'),
            capabilities=dict(experimentalApi=True)), timeout=15)); rpc.send(dict(method='initialized'))
        response=rpc.call('command/exec',dict(command=['/opt/python/bin/python3.11','-I','-B','-c',script,
            linux(secret),'/proc/1/root'+linux(secret)],cwd='/work/actor',
            sandboxPolicy=dict(type='workspaceWrite',writableRoots=['/work/actor'],networkAccess=False),
            timeoutMs=10000),timeout=15)
        save(out/'command.json',response)
        if response.get('exitCode')!=0: raise ValueError('python_runtime_native_command_failed')
        observed=json.loads(response['stdout'])
        if observed['version']!='3.11.18' or observed['uid']!=65534 or observed['tests']!=3 or observed['failures'] or observed['errors']:
            raise ValueError('python_runtime_result_invalid')
        if pins != dict(native=checked_runtime(runtime),python=checked_runtime(python)):
            raise ValueError('python_runtime_postcheck_changed')
        save(out/'results.json',dict(model_calls=0,actual_native_command=True,task_runtime_qualified=True,
            private_canary_unreadable=True,readonly_runtime=True,observed=observed,
            provider_qualified=False,model_recovery_qualified=False,paid_dispatch_admitted=False))
        print(json.dumps(json.loads((out/'results.json').read_text())))
    except BaseException as error:
        save(out/'error.json',dict(type=type(error).__name__,error=str(error),model_calls=0)); raise
    finally:
        if rpc:
            save(out/'methods-issued.json',dict(methods=rpc.sent,model_calls=0))
            if rpc.proc.stdin: rpc.proc.stdin.close()
        cleanup=subprocess.run(['wsl','--terminate','docker-desktop'],capture_output=True,timeout=15)
        save(out/'cleanup.json',dict(exit_code=cleanup.returncode))
        if rpc: rpc.proc.wait(timeout=5); rpc.proc.stdout.close(); rpc.stderr.close()


if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--out',type=Path,required=True)
    p.add_argument('--owned-wsl-distribution',action='store_true',required=True)
    main(p.parse_args().out.resolve())
