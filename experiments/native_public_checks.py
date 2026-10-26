"""Opt-in public acceptance contracts for staged native comparisons.

This is equal availability, not a hidden-test sandbox or proof of semantic
coverage. All requests and test bytes are published before the shared source
task. The parent keeps the returned contract digest outside the task workspace.
"""
import ast
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from native_evidence import digest, file_hash, manifest, read, save
from native_task_checks import require


def publish_contract(workspace, grader, stages, coverage):
    root = Path(workspace).resolve()
    raw = Path(grader).read_bytes()
    tree = ast.parse(raw.decode('utf-8-sig', errors='strict'))
    declared = [node.name + '.' + method.name for node in tree.body if isinstance(node, ast.ClassDef)
                for method in node.body if isinstance(method, ast.FunctionDef) and method.name.startswith('test_')]
    require(declared and len(declared) == len(set(declared)), 'public_check_definitions_invalid')
    require(isinstance(stages, list) and stages, 'public_check_stages_missing')
    ids, used = [], set()
    for stage in stages:
        require(isinstance(stage, dict) and isinstance(stage.get('id'), str) and stage['id']
                and isinstance(stage.get('message'), str) and stage['message'], 'public_check_stage_invalid')
        names = stage.get('methods')
        require(isinstance(names, list) and all(isinstance(n, str) for n in names)
                and len(names) == len(set(names)) and set(names) <= set(declared), 'public_check_names_invalid')
        ids.append(stage['id'])
        used.update(names)
    require(len(ids) == len(set(ids)) and used == set(declared), 'public_check_stage_coverage_invalid')
    require(isinstance(coverage, list) and coverage, 'public_check_coverage_missing')
    covered = set()
    for entry in coverage:
        require(isinstance(entry, dict) and isinstance(entry.get('requirement'), str) and entry['requirement']
                and isinstance(entry.get('boundaries'), str) and entry['boundaries'], 'public_check_coverage_invalid')
        names = entry.get('methods')
        require(isinstance(names, list) and names and all(isinstance(n, str) for n in names)
                and len(names) == len(set(names)) and set(names) <= used, 'public_check_coverage_names_invalid')
        covered.update(names)
    require(covered == used, 'public_check_unmapped_method')
    contract = {'format': 'public_task_checks_v1', 'visibility': 'public_from_initial_source',
                'grader': 'task-contract/checks.py', 'grader_sha256': sha256(raw).hexdigest(),
                'stages': deepcopy(stages), 'coverage': deepcopy(coverage),
                'coverage_status': 'authored_mapping_not_semantic_completeness_proof'}
    area = root / 'task-contract'
    area.mkdir()  # Existing contracts are never overwritten or silently extended.
    with (area / 'checks.py').open('xb') as stream:
        stream.write(raw)
    save(area / 'contract.json', contract)
    return {'contract_sha256': digest(contract),
            'protected_manifest': manifest(area), 'path': str(area / 'contract.json')}


def check_contract(workspace, binding):
    root = Path(workspace).resolve()
    area = root / 'task-contract'
    require(manifest(area) == binding['protected_manifest'], 'public_check_contract_files_changed')
    contract = read(area / 'contract.json')
    require(contract.get('format') == 'public_task_checks_v1' and digest(contract) == binding['contract_sha256']
            and contract['grader'] == 'task-contract/checks.py'
            and file_hash(root / contract['grader']) == contract['grader_sha256'], 'public_check_contract_changed')
    return contract


def grade_public_contract(workspace, binding, stage_id, destination, *, runtime):
    """Run only the registered stage, using the observed task Python executable.

The legacy receipt remains intact; public-receipt.json is the bound observation
returned to the caller. This function makes no native inference calls.
"""
    workspace, destination = Path(workspace).resolve(), Path(destination).resolve()
    contract = check_contract(workspace, binding)
    stage = next((s for s in contract['stages'] if s['id'] == stage_id), None)
    require(stage is not None and stage['methods'], 'public_check_stage_not_executable')
    executable = Path(runtime['executable'])
    require(executable.is_absolute() and file_hash(executable) == runtime['executable_sha256'],
            'public_check_runtime_changed')
    require(not destination.exists(), 'public_check_destination_exists')
    # The worker calls the unchanged grader with sys.executable equal to the task
    # runtime, so its child test process also uses that runtime, not the parent's.
    worker = '''import hashlib,json,pathlib,sys
sys.path.insert(0,sys.argv[1])
from native_task_checks import grade
facts=dict(executable=str(pathlib.Path(sys.executable).resolve()),version=list(sys.version_info[:3]),
 executable_sha256=hashlib.sha256(pathlib.Path(sys.executable).read_bytes()).hexdigest(),
 int_max_str_digits=sys.get_int_max_str_digits())
grade(sys.argv[2],sys.argv[3],json.loads(sys.argv[4]),sys.argv[5])
print(json.dumps(facts))
'''
    process = subprocess.run([str(executable), '-B', '-X', 'utf8', '-c', worker,
        str(Path(__file__).resolve().parent), str(workspace), str(workspace / contract['grader']),
        json.dumps(stage['methods']), str(destination)], capture_output=True, text=True, encoding='utf-8', timeout=40)
    destination.mkdir(parents=True, exist_ok=True)
    for name, value in (('worker-stdout.txt', process.stdout), ('worker-stderr.txt', process.stderr)):
        with (destination / name).open('x', encoding='utf-8') as stream:
            stream.write(value)
    require(process.returncode == 0, 'public_check_worker_failed')
    observed = json.loads(process.stdout)
    require(Path(observed['executable']).resolve() == executable.resolve()
            and observed['executable_sha256'] == runtime['executable_sha256']
            and observed['version'] == runtime['version'], 'public_check_runtime_observation_mismatch')
    check_contract(workspace, binding)
    receipt = read(destination / 'receipt.json')
    executed = destination / 'fixture/tests/_task_grader.py'
    require(file_hash(executed) == contract['grader_sha256'] == receipt['grader_sha256'],
            'public_check_executed_grader_changed')
    require(receipt['names'] == stage['methods'], 'public_check_scope_changed')
    result = {**receipt, 'scope': 'public_contract_named_task_methods', 'contract_sha256': binding['contract_sha256'],
              'contract_stage': stage_id, 'test_visibility': contract['visibility'],
              'observed_runtime': observed, 'legacy_receipt_file_sha256': file_hash(destination / 'receipt.json'),
              'executed_grader_sha256': file_hash(executed)}
    save(destination / 'public-receipt.json', result)
    return result
