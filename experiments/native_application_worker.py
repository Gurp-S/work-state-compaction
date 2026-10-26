"""Eight-stage paired-study worker using the qualified native transport pieces.

Input materialization, paired control comparison and external graders are trusted
adapters passed by the study driver. Semantic selection is native model output;
quality is external evidence, never the task model's own completion claim.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wsc import WSC, Store
from wsc.contracts import Event, digest, encode
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.adapters.recorded_codex import RecordedCodexCheckpointAdapter
from wsc.publication import check_evidence
from native_application_session import NativeApplicationSession
from native_study_fork_session import NativeForkSession
from native_incremental_candidate import prepare, admit_rendered
from native_incremental_generation import generate
from native_evidence import save, file_hash, import_evidence, usage
from native_rollout_snapshot import capture_rollout, parse_rollout
from native_business_delta import split
from native_application_capability import admit as admit_capability
from native_common_prefix import restore as restore_common_prefix
import native_cold_access
from native_fixture_transport import public_binding as fixture_public_binding
from native_typed_content import TypedNativeAdapter,dependencies as media_dependencies


class StopTask(Exception):
    def __init__(self, reason, state='task_failed'):
        self.reason, self.state = reason, state


class ApplicationStudyWorker:
    def __init__(self, conditions, budget, prepare_inputs, admit_pair, grade):
        self.conditions, self.budget = conditions, budget
        self.prepare_inputs, self.admit_pair, self.grade = prepare_inputs, admit_pair, grade

    def __call__(self, job, record_phase):
        output = Path(job['resources']['output'])
        output.mkdir(parents=True, exist_ok=False)
        phases, sessions, paths, grades = [], [], {}, []
        arm_key = job['pair_id'] + '/' + job['arm']
        result = dict(state='infrastructure_error', phases=phases, quality=dict(status='unknown'),
                      conditions_sha256=job['conditions_sha256'], admission_matched=False)
        core, previous, scoped_state = None, None, None
        executed_stages = 0
        pending_tickets = set()

        def open_session(cls, name, registration):
            if 'native_c_auto_compaction' in registration and job['arm'] != 'C':
                raise StopTask('auto_compaction_requires_C_job', 'infrastructure_error')
            session = cls(registration, output / name)
            sessions.append(session)
            session.open()
            admit_capability(session,output/(name+'-capability'))
            paths[session.opened['thread']['id']] = session.opened['thread']['path']
            return session

        def execute(session, name, request, kind='ordinary_phase', schema=None):
            if hasattr(self.admit_pair, 'check'):
                self.admit_pair.check(job)
            try:
                ticket, granted = self.budget.reserve(arm_key, self.conditions['budgets'][kind])
            except ValueError as error:
                if self.budget.snapshot()['study']['uncertain']:
                    raise RuntimeError('study_usage_uncertain') from error
                raise StopTask(str(error), 'budget_exhausted') from error
            save(output / 'grants' / f'{len(phases):03d}.json', dict(ticket=ticket, limits=granted, ledger=self.budget.snapshot()))
            pending_tickets.add(ticket)
            def record(value):
                record_phase(value)  # Persist complete known native evidence first.
                phases.append(value)
                settled = self.budget.settle(ticket, value)
                pending_tickets.remove(ticket)
                save(output / 'budget-settlements' / f'{len(phases)-1:03d}.json', dict(result=settled, ledger=self.budget.snapshot()))
            value = session.execute_stage(request, output / name, granted, record,
                compact=kind == 'boundary_phase' and schema is None and request == 'native_compaction', output_schema=schema)
            if not value.get('usage_complete'):
                raise RuntimeError('native_stage_usage_unknown:' + name)
            if value.get('failure'):
                if value['failure'].startswith('registered_'):
                    raise StopTask(value['failure'], 'budget_exhausted')
                raise RuntimeError('native_stage_failed:' + value['failure'])
            if not value['completed']:
                raise StopTask('native_stage_incomplete')
            return value

        def inject_fact(session, value, name):
            area = output / 'observations' / name
            area.mkdir(parents=True, exist_ok=False)
            item = dict(type='message', role='developer', content=[dict(type='input_text', text=encode(value))])
            path = Path(session.opened['thread']['path'])
            before = path.read_bytes()
            session.server.call('thread/inject_items', dict(threadId=session.opened['thread']['id'], items=[item]))
            after = path.read_bytes()
            if not after.startswith(before):
                raise RuntimeError('observation_source_prefix_changed')
            delta = parse_rollout(after[len(before):])
            items = [r['payload'] for r in delta.rows if r['type'] == 'response_item']
            if not delta.metadata['parse_complete'] or not import_evidence(items, [item])['matched']:
                raise RuntimeError('observation_not_installed')
            save(area / 'fact.json', value)
            capture_rollout(path, archive=area / 'after.jsonl')

        try:
            prepared = self.prepare_inputs(job)
            native_adapter=TypedNativeAdapter(output/'native-media') if self.conditions.get('typed_native_content') else CodexCheckpointAdapter()
            reg = prepared['registration']
            from native_paired_evaluation import load_facts as load_evaluation_facts, as_event as evaluation_event
            evaluation_facts = load_evaluation_facts(reg)
            if reg['model'] != self.conditions['model'] or reg['effort'] != self.conditions['effort']:
                raise RuntimeError('worker_registered_model_mismatch')
            prefix=prepared.get('common_prefix')
            if evaluation_facts is not None and not prefix:
                raise RuntimeError('paired_evaluation_common_prefix_missing')
            if prefix:
                paths.update(reg['parent_paths'])
            initial = open_session(NativeForkSession if prefix else NativeApplicationSession, 'initial', reg)
            session = initial
            self.admit_pair(job, 0, initial)
            result['admission_matched'] = True
            if job['arm'] == 'C':
                core = WSC(Store(output / 'wsc.db', session_id=arm_key, workspace=reg['workspace']), access=lambda *args: True)
            first_turn = prefix['reset_before_turn_id'] if prefix else None
            if prefix:
                result['shared_prefix']=dict(capsule=prefix['capsule'],capsule_sha256=prefix['capsule_sha256'],
                    resumed_after_stage=2,native_S2_turn_completed=False,shared_usage_charged=False)
                runtime_fact=dict(kind='native_execution_transition',current_workspace=reg['workspace'],
                    inherited_context_source='shared_S2',business_manifest_sha256=digest(reg['initial_manifest']),
                    allocated_local_ports=job['resources'].get('ports',[]), **fixture_public_binding(reg))
                inject_fact(initial,runtime_fact,'shared-S2-runtime')
                if evaluation_facts is not None:
                    inject_fact(initial, evaluation_facts, 'shared-S2-evaluation')
                scoped_state = None
                if prepared.get('scoped_selection_state'):
                    from native_scoped_selection_state import load, as_event
                    scoped_state = load(prepared['scoped_selection_state'], receiving_workspace=reg['workspace'])
                    inject_fact(initial, scoped_state, 'scoped-selection-state')
                if core:
                    restore_common_prefix(core,prefix,initial,output/'common-prefix-load.json',native_adapter)
                    core.ingest([Event('common-runtime:'+digest(runtime_fact),'observation',runtime_fact,text=encode(runtime_fact))])
                    if scoped_state is not None:
                        core.ingest([as_event(scoped_state)])
                    if evaluation_facts is not None:
                        core.ingest([evaluation_event(evaluation_facts)])
            for index, stage in enumerate(prepared['stages'], 1):
                if prefix and index < 2:
                    continue
                if not prefix or index > 2:
                    if index == 1:
                        request = prepared['initial_request'] + '\n\n当前交付阶段：\n' + stage['request']
                    else:
                        request = stage['request']
                    phase = execute(session, f'S{index}-phase', request)
                    executed_stages = index
                    snap = parse_rollout((output / f'S{index}-phase/rollout.jsonl').read_bytes())
                    start = phase['turn_accounting']['before']['records']
                    business, host = split(snap.rows[start:])
                    save(output / f'S{index}-host-sources.json', host)
                    if index == 1 and hasattr(self.admit_pair, 'after_first_phase'):
                        wait_start = time.monotonic()
                        try:
                            self.admit_pair.after_first_phase(job, host)
                        finally:
                            self.budget.record_peer_wait(arm_key, time.monotonic() - wait_start)
                    if first_turn is None:
                        first_turn = phase['turn_accounting']['turn_id']
                    if core:
                        ordinal = sum(r['type'] == 'response_item' for r in snap.rows[:start])
                        business_ids = {id(row) for row in business}
                        batch = []
                        for row in snap.rows[start:]:
                            if row['type'] != 'response_item':
                                continue
                            if id(row) in business_ids:
                                batch.extend(native_adapter.import_items([row['payload']], thread_id=phase['thread_id'],
                                    start_ordinal=ordinal, observed_at=[row.get('timestamp')]))
                            ordinal += 1
                        core.ingest(batch)
                        core.presented(f'S{index}-results', tuple(e.id for e in batch if e.kind == 'result'), receiver=phase['thread_id'])
                    if index in (2, 4, 6, 8):
                        grade = self.grade(job, index, output / f'S{index}-acceptance')
                        grades.append(grade)
                        fact = dict(kind='independent_check_observation', stage=f'S{index}',
                            source_manifest_sha256=grade['source_manifest_sha256'], checks=grade['observations'],
                            observed_at=grade['observed_at'], artifact=grade['artifact'])
                        if index < 8:
                            inject_fact(session, fact, f'S{index}-checks')
                        if core:
                            core.ingest([Event(f'check:S{index}:{digest(fact)}', 'observation', fact,
                                text=encode(fact), observed_at=fact['observed_at'])])
                if index not in self.conditions['boundaries']['after_stages']:
                    continue
                old_thread = session.opened['thread']['id']
                if job['arm'] == 'B':
                    execute(session, f'S{index}-compaction', 'native_compaction', kind='boundary_phase')
                    session.close()
                    next_reg = {**reg, 'initial_manifest': session.source_manifest(),
                        'parent_thread_id': old_thread, 'parent_paths': dict(paths)}
                    session = open_session(NativeForkSession, f'S{index}-fork', next_reg)
                else:
                    session.close()
                    selector_reg = {**reg, 'initial_manifest': session.source_manifest(), 'sandbox': 'read-only'}
                    selector = open_session(NativeApplicationSession, f'S{index}-selector', selector_reg)
                    def selected(offered):
                        if self.conditions.get('verify_native_cold_access'):
                            native_cold_access.material(selector,offered,output/f'S{index}-material-access',media_dependencies(core))
                        def run_selection(request, schema):
                            phase = execute(selector, f'S{index}-generation-phase', encode(request),
                                            kind='boundary_phase', schema=schema)
                            return phase, output / f'S{index}-generation-phase/rollout.jsonl'
                        return generate(offered, run_selection, output / f'S{index}-generation',
                            short_span_handles=bool(self.conditions.get('short_span_handles')),
                            **({'scoped_manifest_bindings': True} if scoped_state is not None else {}))
                    try:
                        indexed = bool(self.conditions.get('indexed_checkpoint'))
                        if indexed:
                            from native_indexed_checkpoint import IndexedCheckpointAdapter
                            from wsc.source_reference_view import MODE
                        view = prepare(core, core.capture(), previous, output / 'cold-public', selected,
                            **({'source_projection': MODE} if indexed else {}))
                        if selector.source_manifest() != selector_reg['initial_manifest']:
                            raise RuntimeError('selector_changed_business_source')
                        operation = core.stage(view['view'], directory=output / f'S{index}-exports',
                            archive_directory=output / 'cold-objects',
                            adapter=IndexedCheckpointAdapter() if indexed else RecordedCodexCheckpointAdapter())
                        package = admit_rendered(core.package(operation))
                        check_evidence(core, package)
                        save(output / f'S{index}-package.json', package)
                    except ValueError as error:
                        raise StopTask('candidate_selection_or_export_failed:' + str(error)) from error
                    finally:
                        selector.close()
                    next_reg = {**reg, 'initial_manifest': selector.source_manifest(),
                        'parent_thread_id': prefix['reset_parent_thread_id'] if prefix else initial.opened['thread']['id'],
                        'parent_paths': dict(paths), 'before_turn_id': first_turn}
                    session = open_session(NativeForkSession, f'S{index}-fork', next_reg)
                    session.inject(package['items'])
                    if self.conditions.get('verify_native_cold_access'):
                        native_cold_access.package(session,package,output/f'S{index}-package-access',media_dependencies(core))
                    previous = view['continuation']
                    save(output / f'S{index}-continuation.json', previous)
                    # Native import is audited; no fabricated transactional core receipt.
                    core.discard(operation)
                inject_fact(session, dict(kind='native_execution_transition', active_thread_id=session.opened['thread']['id'],
                    prior_owned_process_tree_closed=True, current_workspace=reg['workspace'],
                    **fixture_public_binding(reg)), f'S{index}-runtime')
                self.admit_pair(job, index // 2, session)
            final_quality = grades[-1]['quality']
            result.update(state='completed' if final_quality['status'] == 'passed' else
                'task_failed' if final_quality['status'] == 'failed' else 'awaiting_review', quality=final_quality,
                executed_stages=8, acceptance=grades)
        except StopTask as error:
            stop = dict(reason=error.reason, state=error.state, phases=len(phases))
            save(output / 'stop-evidence.json', stop)
            result.update(state=error.state, quality=dict(status='failed', evidence_sha256=file_hash(output / 'stop-evidence.json')),
                          reason=error.reason, executed_stages=executed_stages)
        except Exception as error:
            result.update(state='infrastructure_error', error=type(error).__name__ + ':' + str(error))
        finally:
            cleanup = []
            for session in sessions:
                try:
                    cleanup.append(session.close())
                except Exception as error:
                    cleanup.append(dict(error=str(error)))
            if any(c and (c.get('error') or c.get('empty_confirmed') is not True) for c in cleanup):
                result.update(state='infrastructure_error', quality=dict(status='unknown'), cleanup_failed=True)
            result['cleanup'] = cleanup
            if pending_tickets:
                self.budget.mark_unknown(arm_key)
            # Closed native files are authoritative for receipts arriving after
            # the phase snapshot. Never omit them or call their total complete.
            known_ids = {r['response_id'] for p in phases for r in p.get('receipts', {}).get('response_receipts', [])}
            audited = set()
            final_threads = []
            for session in sessions:
                if not session.opened or session.opened['thread']['id'] in audited:
                    continue
                tid = session.opened['thread']['id']
                audited.add(tid)
                try:
                    snap = capture_rollout(session.opened['thread']['path'], archive=output / 'final-threads' / f'{len(final_threads):03d}.jsonl')
                    final_threads.append(dict(thread_id=tid, snapshot=snap.metadata))
                    expected = {r['response_id']:r['usage'] for p in phases if p.get('thread_id') == tid
                                for r in p.get('receipts', {}).get('response_receipts', [])}
                    actual = {r['payload'].get('response_id'):r['payload'].get('usage') for r in snap.rows
                              if r['type'] == 'token_usage_record'}
                    if any(actual.get(rid) != amount for rid,amount in expected.items()):
                        self.budget.mark_unknown(arm_key)
                        result.update(state='infrastructure_error', quality=dict(status='unknown'), final_receipt_binding_changed=True)
                    late = [r for r in snap.rows if r['type'] == 'token_usage_record' and r['payload'].get('response_id') not in known_ids]
                    if late:
                        receipts = usage(late, tid)
                        self.budget.mark_unknown(arm_key, receipts['response_receipts'])
                        extra = dict(seconds=0., usage_complete=False, receipts=receipts, completed=False,
                                     failure='unattributed_native_receipts_after_phase', thread_id=tid)
                        record_phase(extra)
                        phases.append(extra)
                        known_ids.update(r['response_id'] for r in receipts['response_receipts'])
                        result.update(state='infrastructure_error', quality=dict(status='unknown'), late_receipts=True)
                    if not snap.metadata['parse_complete']:
                        self.budget.mark_unknown(arm_key)
                        result.update(state='infrastructure_error', quality=dict(status='unknown'), final_archive_incomplete=True)
                except Exception as error:
                    self.budget.mark_unknown(arm_key)
                    result.update(state='infrastructure_error', quality=dict(status='unknown'), final_archive_error=str(error))
            result['final_threads'] = final_threads
            result['phases'] = phases
            if hasattr(self.admit_pair, 'finished'):
                self.admit_pair.finished(job, result['state'])
            save(output / 'worker-result.json', result)
        return result
