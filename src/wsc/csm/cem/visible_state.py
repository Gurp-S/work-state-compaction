"""Read current and superseded revisions from a single visible source prefix."""
import json
from collections import defaultdict

from ..contracts import parse_instant
from .filters import classify
from ..retrieval import _terms
from ..time_selection import as_of


def visible_state_rows(db, question, *, source_until, visible_source_ids, limit=12, include_unranked=False):
    wanted = set(_terms(question))
    if not wanted or not visible_source_ids:
        return []
    cutoff = parse_instant(source_until)
    grouped = defaultdict(list)
    rows = db.execute('SELECT i.data AS identity, r.data AS revision FROM identities i '
                      'JOIN revisions r ON r.memory_id=i.memory_id ORDER BY i.memory_id, r.revision')
    for row in rows:
        identity, revision = json.loads(row['identity']), json.loads(row['revision'])
        refs = revision.get('source_refs')
        start = revision.get('valid_from') or revision.get('effective_at')
        if (identity.get('merged_into') or not refs or not set(refs) <= visible_source_ids
                or not start or parse_instant(start) > cutoff):
            continue
        grouped[identity['memory_id']].append((identity, revision))

    ranked = []
    for memory_id, pairs in grouped.items():
        identity = pairs[0][0]
        revisions = [revision for _, revision in pairs]
        current = as_of(revisions, source_until)
        older = as_of([revision for revision in revisions if revision is not current], source_until)
        identity_terms = set(_terms(f'{identity["entity"]} {identity["slot"]}'))
        visible_terms = identity_terms | set(_terms(str(current['value'])))
        if older is not None:
            visible_terms |= set(_terms(str(older['value'])))
        score = len(visible_terms & wanted)
        if score or include_unranked:
            ranked.append((score, memory_id, identity, current, older))

    result = []
    for _, _, identity, current, older in sorted(ranked, key=lambda row: (-row[0], row[1]))[:limit]:
        for revision in (current, older):
            if revision is None:
                continue
            label, _ = classify(revision, current['revision'])
            result.append({**revision, 'entity': identity['entity'], 'slot': identity['slot'],
                           'contexts': identity['contexts'],
                           'classification': label,
                           'superseded_by': current['revision'] if revision is older else None})
    return result
