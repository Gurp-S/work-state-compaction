"""Automatic first-checkpoint generation from actual task history and check receipts."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wsc import Limits, Store, Usage, WSC
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.adapters.recorded_codex import RecordedCodexCheckpointAdapter
from wsc.contracts import Event, digest, encode, require
from wsc.publication import check_evidence
from wsc.quote_selection import SelectionDraft
from wsc.span_selection import SpanSelectionGenerator
from native_evidence import save
from native_receipt_identity import receipt_reference
from native_generation_binding import verify_transcript
from native_generation_scope import generation_scope
from native_rollout_snapshot import capture_rollout
from native_phase_observation import record_phase
from native_scope_observation import record_scope, request_scope
from run_quote_selection_probe import output_schema


def checkpoint_sources(area, workspace, source_rollout, source_phase, acceptance, receipt_path, *, generation=True,
                       bind_receipt_file=False):
    """Shared source import; observations retain producer identity and original scope."""
    area, workspace = Path(area), Path(workspace).resolve()
    reference = (receipt_reference(acceptance, Path(receipt_path).resolve()) if bind_receipt_file else
                 {'receipt_path': str(Path(receipt_path).resolve()), 'receipt_sha256': digest(acceptance)})
    area.mkdir()
    snapshot = capture_rollout(source_rollout)
    require(snapshot.metadata['sha256'] == source_phase['rollout_sha256'], 'checkpoint_source_changed')
    scope = generation_scope(snapshot, source_phase, workspace)
    metadata = [row['payload'] for row in snapshot.rows if row['type'] == 'session_meta']
    require(len(metadata) == 1 and metadata[0].get('id') == source_phase['thread_id'],
            'checkpoint_source_thread_mismatch')
    require(Path(scope['source_execution']['workspace']).resolve() == workspace,
            'checkpoint_source_workspace_mismatch')
    history = [r for r in snapshot.rows if r['type'] == 'response_item']
    core = WSC(Store(area / 'state.db', session_id=area.name, workspace=str(workspace)), access=lambda *a: True)
    batch = CodexCheckpointAdapter().import_items([r['payload'] for r in history],
        thread_id=source_phase['thread_id'], observed_at=[r.get('timestamp') for r in history])
    core.ingest(batch)
    core.presented('archived-task-presentation', tuple(e.id for e in batch if e.kind == 'result'),
                   receiver='checkpoint_material_builder:' + source_phase['thread_id'])
    public = {k: acceptance[k] for k in ('observed_at', 'source_manifest_sha256', 'names', 'tests',
                                        'passed', 'scope', 'grader_sha256')}
    public.update(reference)
    public.update(kind='independent_named_check_observation',
                  source_workspace=str(workspace),
                  failed_methods=[entry['test'] for entry in acceptance.get('failures', [])],
                  errored_methods=[entry['test'] for entry in acceptance.get('errors', [])],
                  skipped_methods=acceptance.get('skipped'))
    core.ingest([Event('task-check:' + digest(acceptance), 'observation', acceptance,
                       text=encode(public), observed_at=acceptance['observed_at'])])
    record_phase(core, snapshot, source_phase)
    binding = None
    if generation:
        binding = record_scope(core, snapshot, source_phase, workspace,
                               observed_at=datetime.now(timezone.utc).isoformat())
    original = core.material(core.capture())
    save(area / 'original-material.json', original)
    return core, original, binding, scope


def export_checkpoint(core, area, view, result, *, adapter=None):
    operation = core.stage(view, directory=area / 'exports',
                           adapter=adapter if adapter is not None else RecordedCodexCheckpointAdapter())
    package = core.package(operation)
    check_evidence(core, package)
    save(area / 'package.json', package)
    result.update(view=view, operation=operation, rendered_bytes=len(encode(package['items']).encode('utf-8')))
    return package


def generate_checkpoint(area, workspace, source_rollout, source_phase, acceptance, receipt_path, execute):
    """execute(request, schema) returns (native phase outcome, archived rollout path)."""
    area = Path(area)
    core, original, binding, scope = checkpoint_sources(
        area, workspace, source_rollout, source_phase, acceptance, receipt_path)
    result = {'status': 'started', 'scope': 'automatic_first_checkpoint; no installation receipt'}
    def generate(offered):
        request = {'operation': 'working_state_selection',
            'task_request': '继续处理当前任务状态和后续用户要求。',
            'execution_scope': request_scope(original, binding, scope),
            'source_status': 'Archived task observations and a named check receipt; selection generation only.',
            'output_contract': {
                'source_ids': 'Selected original records by source alias.',
                'understanding_refs': 'Selected existing model-record revisions.',
                'new_understandings': 'Revisable model understanding with exact source aliases.',
                'clues': 'Model-selected discovery text with source aliases.',
                'span_refs': 'Exact selected span identities; original text compiled outside the model.'},
            'material': offered}
        schema = output_schema(offered, 'span')
        save(area / 'request.json', request)
        save(area / 'schema.json', schema)
        phase, archive = execute(request, schema)
        known = Usage()
        if phase.get('usage_complete'):
            u = phase['receipts']['all_usage']
            known = Usage(u['input_tokens'] - u['cached_input_tokens'], u['cached_input_tokens'], u['output_tokens'])
        try:
            require(phase.get('usage_complete') and phase['completed'] and not phase['failure']
                    and len(phase['finals']) == 1, 'checkpoint_generation_incomplete')
            observed = capture_rollout(archive)
            require(observed.metadata['parse_complete'] and
                    observed.metadata['sha256'] == phase['rollout_sha256'], 'checkpoint_generation_archive_changed')
            proof, actual = verify_transcript(observed, phase)
            require(actual == request, 'checkpoint_generation_request_changed')
            save(area / 'generation-binding.json', proof)
            draft = json.loads(phase['finals'][0]['text'])
            save(area / 'model-draft.json', draft)
            return SelectionDraft(draft, known)
        except Exception as exc:
            exc.usage = known
            raise
    try:
        view = core.generate(core.capture(), SpanSelectionGenerator(generate, boundary_policy='word',
            max_material_bytes=524288), producer='native_model', include_selection_facts=True,
            limits=Limits(max_material_bytes=524288, max_view_bytes=262144))
        package = export_checkpoint(core, area, view, result)
        result.update(status='generated_compiled_exported')
        return package
    except Exception as exc:
        result.update(status='failed_preserved', error=type(exc).__name__ + ':' + str(exc))
        raise
    finally:
        result.update(usage=core.status()['usage'], cursor=core.status()['cursor'])
        save(area / 'result.json', result)
