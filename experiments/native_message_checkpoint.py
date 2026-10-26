"""Experimental reuse of authored messages and producer observations, without generation.

This is a first-checkpoint policy, not a semantic completeness claim or general
long-horizon selector. Full original sources remain in the ordinary cold archive.
"""
from pathlib import Path

from native_evidence import save
from native_task_checkpoint import checkpoint_sources, export_checkpoint
from wsc import Limits, Selection


def prepare_message_checkpoint(area, workspace, source_rollout, source_phase, acceptance, receipt_path, *, adapter=None,
                               bind_receipt_file=False):
    area = Path(area)
    core, _, _, _ = checkpoint_sources(area, workspace, source_rollout, source_phase, acceptance, receipt_path,
                                       generation=False, bind_receipt_file=bind_receipt_file)
    result = {'status': 'started', 'scope': 'original messages and producer observations; no installation receipt',
              'generation_calls': 0, 'policy': 'all_message_and_observation_events_v1'}
    try:
        snapshot = core.capture()
        selected = tuple(row['id'] for row in snapshot.events if row['kind'] in {'message', 'observation'})
        selection = Selection(source_ids=selected)
        save(area / 'selection.json', {'source_ids': selected, 'source_digest': snapshot.source_digest,
                                     'policy': result['policy']})
        view = core.prepare(snapshot, selection, producer='original_message_projection',
                            limits=Limits(max_view_bytes=262144))
        package = export_checkpoint(core, area, view, result, adapter=adapter)
        result.update(status='prepared_exported', selected_sources=len(selected), source_count=snapshot.cut)
        return package
    except Exception as exc:
        result.update(status='failed_preserved', error=type(exc).__name__ + ':' + str(exc))
        raise
    finally:
        result.update(usage=core.status()['usage'], cursor=core.status()['cursor'])
        save(area / 'result.json', result)
