"""Opt-in bench reader of reviewed CSM commitment state."""
from csm_bench22 import CsmBench22
from wsc.csm.commitment_projection import commitments_due
from wsc.csm.contracts import parse_instant
from wsc.csm.store import getmeta


class CsmBench22Commitments(CsmBench22):
    name = 'csm-reviewed-commitments'

    def retrieve(self, question, now, cutoff_turn, item_id=None, *, _reviewed_state=()):
        stop = min(len(self.turns), cutoff_turn)
        if stop < 1:
            return super().retrieve(question, now, cutoff_turn, item_id=item_id, _reviewed_state=_reviewed_state)
        with self.store.connect() as db:
            ready = getmeta(db, 'property_journal_format') is not None
        if not ready:
            return super().retrieve(question, now, cutoff_turn, item_id=item_id, _reviewed_state=_reviewed_state)

        cutoff = min(now, self.turns[stop - 1]['time'], key=parse_instant)
        source_ids = {f'chat/{t["turn"]}': t['turn'] for t in self.turns[:stop]}
        due = commitments_due(self.csm, now=now, source_until=cutoff, visible_source_ids=source_ids)
        # The shared state bundle now owns due publication.  Keep the reviewed
        # source turns for used_turns, but do not duplicate the due block.
        turns = set()
        for item in due:
            turns.update(source_ids[span['event_id']] for span in item['evidence'])
        return self._retrieve(question, cutoff_turn, now=now, state_turns=turns, reviewed_state=_reviewed_state)
