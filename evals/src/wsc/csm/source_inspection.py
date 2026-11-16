"""Explicit, read-only inspection of one declared memory revision's sources.

This operation does not choose an answer-bearing memory for the caller, rank
global memories, merge identities, or replace an existing retrieval packet.
"""
from collections import Counter
import json
from ..contracts import digest
from . import assembly, filters
from .contracts import require, parse_instant, validate_instant
from .evidence_recall import _source_units, _content
from .recall_terms import terms
from .recall_scoring import overlap_weight


def inspect(db, memory_id, *, revision, expected_value, limit=3, max_chars=4000, until=None):
    require(isinstance(memory_id, str) and bool(memory_id), 'inspection_memory_id_invalid')
    require(type(revision) is int and revision > 0, 'inspection_revision_invalid')
    require(type(limit) is int and 0 < limit <= 15, 'inspection_limit_invalid')
    require(type(max_chars) is int and max_chars >= 512, 'inspection_budget_invalid')
    cutoff = parse_instant(validate_instant(until, field='until')) if until else None
    row = db.execute('SELECT data FROM revisions WHERE memory_id=? AND revision=?',
                     (memory_id, revision)).fetchone()
    require(row is not None, 'inspection_revision_missing')
    selected = json.loads(row['data'])
    require(digest(selected.get('value')) == digest(expected_value), 'inspection_value_mismatch')
    if cutoff and selected.get('valid_from'):
        require(parse_instant(selected['valid_from']) <= cutoff, 'inspection_revision_outside_cutoff')
    refs = selected.get('source_refs') or []
    require(bool(refs), 'inspection_sources_missing')
    candidates, actor_words = [], set()
    focus = filters.enabled('source_focus')
    centers = []
    for ref in refs:
        event = db.execute('SELECT observed_at,data,digest FROM events WHERE id=?', (ref,)).fetchone()
        require(event is not None, 'inspection_source_missing')
        if cutoff:
            require(bool(event['observed_at']) and parse_instant(event['observed_at']) <= cutoff,
                    'inspection_source_outside_cutoff')
        payload = json.loads(event['data'])
        require(digest(payload) == event['digest'], 'evidence_source_digest_mismatch')
        by_turn = {}
        if isinstance(payload, dict) and isinstance(payload.get('turns'), list):
            for index, turn in enumerate(payload['turns']):
                if isinstance(turn, dict):
                    actor_words.update(terms(str(turn.get('speaker') or '')))
                    if focus:
                        by_turn[str(turn.get('dia_id') or index)] = turn
        for suffix, unit in _source_units(payload, neighborhood=True):
            candidates.append({'memory_id': 'event:' + ref + ('#' + suffix if suffix else ''),
                'record_type': 'source_event', 'value': unit, 'source_refs': [ref],
                'classification': 'UNKNOWN', 'confirmed': False,
                'reason': 'declared_revision_source',
                'source_scope': 'dialogue_window' if suffix else 'observed_event'})
            if focus:
                centers.append(by_turn.get(suffix))
    wanted = terms(_content(expected_value)) - actor_words
    bags = [terms(_content(row['value'])) - actor_words for row in candidates]
    frequency = Counter(term for bag in bags for term in bag)
    scores = [overlap_weight(wanted & bag, frequency, len(bags)) for bag in bags]
    strongest = max(scores, default=0)
    ranked = [i for i, score in enumerate(scores) if score > 0 and score == strongest]
    if focus:
        from .source_focus import rank_tied_windows
        ranked = rank_tied_windows(ranked, candidates, centers, wanted, frequency, len(bags))
    else:
        ranked.sort(key=lambda i: candidates[i]['memory_id'])
    results = [candidates[i] for i in ranked]
    packet = assembly.assemble({'results': results,
        'counts': dict(Counter(r['classification'] for r in results))}, max_items=limit, max_chars=max_chars)
    packet.update({'policy': 'declared-source-inspection-v1',
        'anchor': {'memory_id': memory_id, 'revision': revision},
        'declared_source_refs': list(refs), 'source_validation': 'digest_checked',
        'state_scope': 'declared_identity_revision_not_world_confirmation',
        'context_binding': 'literal_within_declared_sources' if results else 'not_established',
        'completeness': 'not_established'})
    for item in packet['items']:
        item['source_refs'] = item['evidence']
    while True:
        size = len(json.dumps(packet, ensure_ascii=False, separators=(',', ':')))
        if size > max_chars:
            require(bool(packet['items']), 'inspection_metadata_exceeds_budget')
            packet['items'].pop(); packet['omitted'] += 1; packet['truncated'] = True
        elif packet['used_chars'] != size:
            packet['used_chars'] = size
        else:
            return packet
