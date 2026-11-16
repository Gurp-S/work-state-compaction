"""Run one WSC arm with P0-only config against the same fixture."""
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import yaml

import host_pair as hp

HERE = Path(__file__).resolve().parent
HOME = Path.home() / '.dsh'
SRC = HOME / 'profiles' / 'ab-goal-675a608-wsc'
DST = HOME / 'profiles' / 'ab-goal-p0-wsc'
STAGE = HERE / 'host-pair-p0'
HASH = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()

if DST.exists():
    shutil.rmtree(DST)
shutil.copytree(SRC, DST)
patch = yaml.safe_load((DST / 'cordis.patch.yml').read_text(encoding='utf-8'))
for row in patch:
    if row.get('id') == 'wsc-config':
        row['config'].pop('state', None)
        row['config'].pop('workingset', None)
(DST / 'cordis.patch.yml').write_text(yaml.safe_dump(patch, sort_keys=False), encoding='utf-8')

if STAGE.exists():
    shutil.rmtree(STAGE)
STAGE.mkdir()
temp = Path(tempfile.mkdtemp(prefix='codex-wsc-p0-'))
work = temp / 'task'
shutil.copytree(hp.SOURCE / 'fixture-constraint', work)
spec = {'profile': DST.name, 'profile_dir': str(DST), 'work': str(work),
        'patch_sha256': HASH(DST / 'cordis.patch.yml')}
hp.STAGE = STAGE
hp.preflight({'wsc': spec})
hp.run('wsc-p0', spec)
print(json.dumps(json.loads((STAGE / 'wsc-p0-result.json').read_text(encoding='utf-8')), indent=2))
