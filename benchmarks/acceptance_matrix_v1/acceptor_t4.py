"""Browser behavior checks, never a screenshot beauty or model score."""
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent


def accept_t4(workspace, *, screenshot=None, smoke=False):
    command = [shutil.which('node'), str(ROOT/'t4_browser_checks.cjs'), str(Path(workspace).resolve())]
    if screenshot is not None:
        command += ['--screenshot', str(Path(screenshot).resolve())]
    if smoke:
        command += ['--smoke']
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
    if result.returncode:
        raise RuntimeError('browser_acceptor_environment_or_protocol_failure: ' + result.stderr.decode('utf-8')[:2000])
    return json.loads(result.stdout.decode('utf-8'))
