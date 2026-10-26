"""Verify task Python inside the native sandbox before paying for a model turn."""
import json
from pathlib import Path

from native_evidence import save

PROBE = '''import hashlib,json,sqlite3,sys,unittest
db=sqlite3.connect(':memory:'); value=db.execute('select 7').fetchone()[0]; db.close()
print(json.dumps(dict(executable=sys.executable,executable_sha256=hashlib.sha256(open(sys.executable,'rb').read()).hexdigest(),version=list(sys.version_info[:3]),sqlite_version=sqlite3.sqlite_version,sqlite_result=value,unittest_available=hasattr(unittest,'TestCase'))))
'''


def verify_runtime(server, workspace, command, destination):
    destination = Path(destination)
    destination.mkdir()
    request = {'command': [*command, '-B', '-X', 'utf8', '-c', PROBE], 'cwd': str(workspace),
        'sandboxPolicy': {'type': 'workspaceWrite', 'writableRoots': [], 'networkAccess': False,
                          'excludeTmpdirEnvVar': False, 'excludeSlashTmp': False}, 'timeoutMs': 15000}
    save(destination / 'request.json', request)
    result = {'model_calls': 0, 'status': 'failed', 'command': command}
    try:
        response = server.call('command/exec', request, timeout=25)
        result['response'] = response
        if response.get('exitCode') != 0:
            raise ValueError('task_python_exit_nonzero')
        facts = json.loads(response['stdout'])
        if not (facts['version'][:2] == [3, 11] and facts['sqlite_result'] == 7 and facts['unittest_available']
                and Path(facts['executable']).is_absolute() and len(facts['executable_sha256']) == 64):
            raise ValueError('task_python_capability_mismatch')
        if Path(command[0]).is_absolute() and Path(facts['executable']).resolve() != Path(command[0]).resolve():
            raise ValueError('task_python_executable_changed')
        result.update(status='passed', facts=facts)
        return {'kind': 'observed_task_python_runtime', 'command': command, **facts}
    except Exception as exc:
        result['error'] = type(exc).__name__ + ':' + str(exc)
        raise ValueError('native_task_runtime_unavailable') from exc
    finally:
        save(destination / 'result.json', result)
