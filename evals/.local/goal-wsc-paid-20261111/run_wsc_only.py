"""Run ONLY the wsc arm of an already-prepared isolated stage.

Reuses host_pair.py's exact run()/preflight() logic so the produced
wsc-result.json + seals are identical to a full run, but skips native
(per explicit request: native already 18/18 and config-insensitive here).
"""
import json
import sys
from pathlib import Path

HERE = Path(r'D:\lea\XenYon code\wsc\.local\goal-wsc-paid-20261111')
sys.path.insert(0, str(HERE))
import host_pair  # noqa: E402

STAGE = HERE / 'host-pair-v21-isolated'
HOME = STAGE / 'dsh-home'
host_pair.STAGE = STAGE
host_pair.HOME = HOME

specs = json.loads((STAGE / 'setup.json').read_bytes())
# Preflight only the wsc arm; native is left untouched.
host_pair.preflight(specs, ['wsc'])
ok = host_pair.run('wsc', specs['wsc'])
print('WSC run ok:', ok)
sys.exit(0 if ok else 1)
