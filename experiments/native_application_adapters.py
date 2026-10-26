"""Frozen-input materializer and external automatic-grade adapter for study workers."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys

from native_evidence import digest, file_hash, manifest, read, save
from native_owned_process import ProcessOwner
from native_application_quality import settle_quality
from native_private_input_reuse import verify as verify_reuse
from native_application_capability import materialize as materialize_browser


def streamed_hash(path):
    h = sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


class FrozenApplicationAdapters:
    def __init__(self, conditions, tasks, expected_checks, *, node_executable):
        self.conditions, self.tasks, self.expected_checks = conditions, tasks, expected_checks
        self.node = node_executable

    def prepare(self, job):
        task_id = job['pair_id'].split('/')[0]
        spec = self.tasks[task_id]
        if file_hash(spec['binding']) != spec['binding_sha256']:
            raise ValueError('application_input_binding_changed')
        binding = read(spec['binding'])
        frozen = Path(binding['workspace'])
        if manifest(frozen) != binding['source_manifest']:
            raise ValueError('application_frozen_input_changed')
        work = Path(job['resources']['workspace'])
        reuse = self.conditions.get('private_input_reuse', {}).get(job['pair_id']+'/'+job['arm'])
        reuse_evidence = None
        if reuse:
            if reuse['binding_sha256'] != spec['binding_sha256']:
                raise ValueError('application_reuse_input_binding_mismatch')
            reuse_evidence = verify_reuse(reuse, job, binding)
        else:
            shutil.copytree(frozen, work)
            if manifest(work) != binding['source_manifest']:
                raise ValueError('application_private_source_copy_changed')
        if task_id == 'a3':
            deps = read(binding['dependency_manifest'])
            if file_hash(binding['dependency_manifest']) != binding['dependency_manifest_sha256']:
                raise ValueError('application_dependency_binding_changed')
            source = Path(binding['dependency_base'])
            target = work / 'gui/node_modules'
            if not reuse:
                target.mkdir()
            def copy(item):
                key, expected = item
                relative = PurePosixPath(key)
                if relative.is_absolute() or '..' in relative.parts or ':' in key or '\\' in key:
                    raise ValueError('application_dependency_relative_path_invalid')
                src, dst = source / key, target / key
                if src.is_symlink():
                    raise ValueError('application_dependency_link')
                if reuse:
                    if dst.is_symlink() or dst.stat().st_nlink != 1:
                        raise ValueError('application_dependency_reuse_not_private')
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dst)
                if streamed_hash(dst) != expected:
                    raise ValueError('application_dependency_copy_changed')
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(copy, deps['files'].items()))
            if reuse:
                actual_keys = {p.relative_to(target).as_posix() for p in target.rglob('*') if p.is_file()}
                if actual_keys != set(deps['files']):
                    raise ValueError('application_dependency_reuse_inventory_changed')
            draft = read(work / 'task-contract/a3-ui-long-v1/task-draft.json')
            task_text = json.dumps({key:draft[key] for key in ('common_brief','design_requirements','existing_semantics_to_preserve','stages')},
                                   ensure_ascii=False,indent=2)
            stages = draft['stages']
            contract_paths = ['task-contract/a3-ui-long-v1/public-contract.json',
                              'task-contract/a3-ui-long-v1/harness/run-acceptance.mjs']
        else:
            draft = read(work / f'task-contract/tasks/{task_id}/task.json')
            task_text = (work / 'task-contract/COMMON.md').read_text(encoding='utf8') + '\n\n' + (
                work / f'task-contract/tasks/{task_id}/TASK.md').read_text(encoding='utf8')
            stages = draft['stages']
            contract_paths = ['task-contract/acceptance/run.py','task-contract/acceptance/manual-review.md']
        registration = dict(workspace=str(work), initial_manifest=binding['source_manifest'],
            executable=self.conditions['executable']['path'], executable_sha256=self.conditions['executable']['sha256'],
            model=self.conditions['model'], effort=self.conditions['effort'],
            manifest_excludes=['gui/node_modules','gui/dist','gui/.wsc-cache','gui/.vite','gui/tsconfig.tsbuildinfo'])
        if self.conditions.get('host_feature_overrides'):
            registration['host_feature_overrides'] = self.conditions['host_feature_overrides']
        if self.conditions.get('browser_runtime') and task_id=='a3':
            registration.update(materialize_browser(work,self.conditions['browser_runtime']))
            registration['node_executable']=self.node
            registration['manifest_excludes'].append('.wsc-runtime')
            registration['manifest_excludes'].append('.wsc-probes')
        if task_id == 'a3' and self.conditions.get('fixture_transport'):
            from native_fixture_transport import attach, MODE
            if self.conditions['fixture_transport'] != MODE:
                raise ValueError('application_fixture_transport_unsupported')
            registration = attach(registration, frozen)
            contract_paths[1] = str(Path(registration['fixture_root']) / 'harness/run-acceptance.mjs')
        from native_paired_evaluation import configure
        registration = configure(registration, frozen, self.conditions)
        if registration.get('evaluation_host'):
            contract_paths[1] = str(Path(registration['fixture_root']) / 'harness/run-acceptance.mjs')
        request = ('完成下面这个独立应用副本的开发任务，交付精致、可实际操作的界面及完整业务能力。全部阶段需求从开始即可见，当前按阶段交付。\n'
            + json.dumps(dict(current_workspace=str(work), source_document_absolute_paths='Original repository identifiers; this copy has the same relative source paths',
                allocated_local_ports=job['resources']['ports'], public_acceptance_files=contract_paths,
                python_runtime=[sys.executable,'-B','-X','utf8'], node_runtime=self.node),ensure_ascii=False)
            + '\n完整任务合同：\n' + task_text)
        save(Path(job['resources']['output']) / 'prepared-input.json', dict(task_id=task_id,
            binding=spec['binding'], binding_sha256=spec['binding_sha256'], registration=registration,
            reuse=reuse_evidence,
            dependency_copy='physical_private' if task_id=='a3' else None))
        return dict(registration=registration, stages=stages, initial_request=request)

    def grade(self, job, stage, destination):
        task_id = job['pair_id'].split('/')[0]
        spec = self.tasks[task_id]
        binding = read(spec['binding'])
        frozen = Path(binding['workspace'])
        protected = {k:v for k,v in binding['source_manifest'].items() if k.startswith('task-contract/')}
        if any(file_hash(frozen / key) != value for key,value in protected.items()):
            raise ValueError('application_external_grader_changed')
        work, output = Path(job['resources']['workspace']), Path(destination)
        output.parent.mkdir(parents=True,exist_ok=True)
        if task_id=='a3':
            grader = frozen / 'task-contract/a3-ui-long-v1/harness/run-acceptance.mjs'
            if self.conditions.get('fixture_transport'):
                from native_fixture_transport import verify, MODE
                if self.conditions['fixture_transport'] != MODE:
                    raise ValueError('application_fixture_transport_unsupported')
                grader = verify(work / '.wsc-runtime/fixture-transport-v1', frozen)
            from native_paired_evaluation import grade_path
            grader = grade_path(work, frozen, self.conditions, grader)
            command = [self.node,str(grader),str(work/'gui'),str(output),f'S{stage}']
        else:
            grader = frozen / 'task-contract/acceptance/run.py'
            command = [sys.executable,'-B','-X','utf8',str(grader),task_id,str(work),str(output),'--stage',str(stage)]
        logroot = output.parent / (output.name+'-driver')
        logroot.mkdir(exist_ok=False)
        owner = ProcessOwner()
        proc = None
        code, error = None, None
        with (logroot/'stdout.txt').open('x',encoding='utf8') as stdout, (logroot/'stderr.txt').open('x',encoding='utf8') as stderr:
            try:
                proc = subprocess.Popen(command,cwd=work,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
                                        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                owner.attach(proc)
                code = proc.wait(timeout=240)
            except Exception as caught:
                error = type(caught).__name__ + ':' + str(caught)
            finally:
                try:
                    cleanup = owner.close()
                finally:
                    if proc is not None and proc.poll() is None:
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait(timeout=5)
        save(logroot/'process.json',dict(command=command,exit_code=code,cleanup=cleanup,error=error))
        if error or code != 0 or not (output/'result.json').is_file():
            raise RuntimeError('external_grader_did_not_complete:' + str(output))
        result, registration = read(output/'result.json'), read(output/'registration.json')
        outcomes = result['outcomes']
        expected = self.expected_checks[task_id][str(stage)]
        if {row['id'] for row in outcomes} != set(expected) or len(outcomes)!=len(expected):
            raise RuntimeError('external_grader_scope_incomplete')
        receipts = []
        for row in outcomes:
            path = output/(row['id']+'.json') if task_id=='a3' else output/row['id']/'receipt.json'
            observed = read(path)
            if observed['id'] != row['id'] or observed['passed'] is not row['passed']:
                raise RuntimeError('external_grader_receipt_mismatch')
            receipts.append(dict(id=row['id'],passed=row['passed'],receipt=str(path)))
        if task_id=='a3':
            current = manifest(work/'gui/src')
            auxiliary = dict(package_sha256=file_hash(work/'gui/package.json'), lock_sha256=file_hash(work/'gui/package-lock.json'))
        else:
            current = {p.relative_to(work).as_posix():file_hash(p) for p in sorted(work.rglob('*')) if p.is_file()
                and not any(part in ('__pycache__','node_modules','.git') for part in p.relative_to(work).parts)}
            auxiliary = {}
        if registration['source_manifest'] != current:
            raise RuntimeError('external_grader_source_no_longer_current')
        files = {str(path):file_hash(path) for path in [output/'registration.json',output/'result.json',*(Path(r['receipt']) for r in receipts)]}
        evidence = dict(kind='a3' if task_id=='a3' else 'http',source_manifest=current,auxiliary=auxiliary,files=files,
            registration_path=str(output/'registration.json'),result_path=str(output/'result.json'),automatic=receipts,manual=[],
            grader_manifest=registration['harness_manifest' if task_id=='a3' else 'acceptance_manifest'])
        manual_ids = ['ui_workflows','visual_responsive_themes','keyboard_and_errors','source_and_uncovered_edges']
        quality = settle_quality(evidence,current,expected,manual_ids,current_auxiliary=auxiliary) if stage==8 else dict(status='unknown',reason='intermediate_stage')
        save(logroot/'quality-binding.json',evidence)
        return dict(quality=quality,source_manifest_sha256=digest(current),observed_at=datetime.now(timezone.utc).isoformat(),
            observations=[dict(id=r['id'],passed=r['passed']) for r in receipts], artifact=str(output/'result.json'),
            manual_requirements=manual_ids, manual_pending=True)
