"""Real TypeScript type checking and independent runtime caller checks."""
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
COMPILER = ROOT.parents[2]/'gui/node_modules/typescript/bin/tsc'
CLIENTS = ('api', 'cli', 'dashboard', 'exporter', 'worker')
PROBE = """import {listUsage, Row, Query, Page} from './api';
const rows: Row[] = [];
const query: Query = {tenant:'t',model:{provider:'p',name:'m'}};
const page: Page = listUsage(rows,query);
// @ts-expect-error Legacy positional API is not accepted by the new contract.
listUsage(rows,'t','m');
"""


def accept_t2(workspace):
    workspace = Path(workspace).resolve()
    node = shutil.which('node')
    if node is None or not COMPILER.is_file():
        raise RuntimeError('typescript_runtime_unavailable')
    with tempfile.TemporaryDirectory(prefix='matrix-t2-') as folder:
        work = Path(folder)
        total = 0
        paths = []
        for source in workspace.rglob('*.ts'):
            relative = source.relative_to(workspace)
            if any(part in ('node_modules', 'dist', 'build') for part in relative.parts):
                continue
            if not source.resolve().is_relative_to(workspace):
                raise ValueError('typescript_source_outside_workspace')
            raw = source.read_bytes()
            total += len(raw)
            if total > 1048576 or len(paths) >= 256:
                raise ValueError('typescript_fixture_source_budget_exhausted')
            target = work/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            paths.append(str(target))
        if any(not (work/(name+'.ts')).is_file() for name in CLIENTS):
            raise ValueError('typescript_required_artifact_missing')
        probe = work/'coordinator_type_contract.ts'
        if probe.exists():
            raise ValueError('coordinator_type_contract_name_conflict')
        probe.write_text(PROBE, encoding='utf-8')
        command = [node, str(COMPILER), '--strict', '--skipLibCheck', '--target', 'ES2020',
                   '--module', 'commonjs', '--lib', 'ES2020,DOM', '--noEmitOnError',
                   '--outDir', str(work/'compiled'), *paths, str(probe)]
        compiled = subprocess.run(command, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
        rows = [dict(check_id='typescript-contract', passed=compiled.returncode == 0,
                     constraint_id='public-api-shape')]
        if compiled.returncode:
            rows[0]['reason'] = compiled.stdout.decode('utf-8', errors='strict')[:12000]
            return dict(task='T2', success=False, checks=rows, runtime_checks_not_run=12,
                        constraint_violations=['public-api-shape'])
        result = subprocess.run([node, str(ROOT/'t2_runtime_checks.cjs'), str(work/'compiled')],
                                cwd=work, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        if result.returncode:
            return dict(task='T2', success=False, checks=rows+[dict(check_id='runtime-import', passed=False,
                constraint_id=None, reason=result.stderr.decode('utf-8', errors='strict')[:12000])],
                runtime_checks_not_run=12, constraint_violations=[])
        rows += json.loads(result.stdout.decode('utf-8'))['checks']
        return dict(task='T2', success=all(row['passed'] for row in rows), checks=rows,
                    runtime_checks_not_run=0, compiler_sha256=sha256(COMPILER.read_bytes()).hexdigest(),
                    constraint_violations=sorted({r['constraint_id'] for r in rows if not r['passed'] and r['constraint_id']}),
                    scope='Strict compiler and runtime contracts; not a model evaluation.')
