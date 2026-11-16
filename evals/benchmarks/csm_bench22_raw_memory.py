"""Offline full-source memory candidate for the Bench 2.2 adapter."""
from csm_bench22 import CsmBench22, StateRetrieval
from csm_bench22_candidate_state import candidate_scope
from csm_bench22_passages import source_passage
from csm_bench22_passage_binding import narrow_passage_candidates, verify_passage
from csm_bench22_phrase_recall import PhraseIndex
from csm_bench22_recall_lanes import PassageIndex, rank_passages_in_turn
from csm_bench22_scope import visible_observations
from csm_bench22_state import CalendarEvidence
from wsc.csm.commitment_projection import reviewed_commitments_from_sources
from wsc.csm.contracts import CSMError, parse_instant


class RawMemoryBench22(CsmBench22):
    """Retain complete source payloads and leave state production to reviewed state."""

    def __init__(self, *, revision_state=False, append_passages=False, recall_lanes=False, phrase_recall=False,
                 sentence_passages=False, store=None, require_commitment_scope=False,
                 recall_commitment_candidates=False, state_extractor=None, annotate_evidence_dates=False):
        if recall_commitment_candidates and not (require_commitment_scope and recall_lanes):
            raise ValueError('commitment_candidate_recall_requires_scoped_passage_index')
        super().__init__(None, state_extractor=state_extractor, revision_state=revision_state, store=store,
                         require_commitment_scope=require_commitment_scope)
        self.append_passages = append_passages
        self.recall_commitment_candidates = recall_commitment_candidates
        self.annotate_evidence_dates = annotate_evidence_dates
        self.passage_index = PassageIndex(sentences=sentence_passages) if recall_lanes else None
        self.date_index = CalendarEvidence() if recall_lanes else None
        self.phrase_index = PhraseIndex() if phrase_recall else None

    def _source_payload(self, turn):
        return dict(turn)

    def _index_source(self, turn):
        super()._index_source(turn)
        if self.phrase_index is not None:
            self.phrase_index.add(turn)
        if self.passage_index is not None:
            self.passage_index.add(turn)
            self.date_index.add(turn)

    def rewind(self, token):
        dropped = self.turns[token:] if self.phrase_index is not None else ()
        super().rewind(token)
        if dropped:
            self.phrase_index.rewind(dropped)
        if self.passage_index is not None:
            self.passage_index.rewind(token)
            self.date_index.rewind(token)

    def read_original(self, turn, *, now, cutoff_turn):
        if (type(turn) is not int or type(cutoff_turn) is not int or not 1 <= turn <= min(len(self.turns), cutoff_turn)
                or parse_instant(self.turns[turn - 1]['time']) > parse_instant(now)):
            raise ValueError('source_outside_visible_history')
        return self._source(turn - 1)

    def _search_scope(self, now, cutoff_turn, limit):
        if type(limit) is not int or not 1 <= limit <= 32:
            raise ValueError('invalid_source_search_limit')
        if type(cutoff_turn) is not int or cutoff_turn < 0:
            raise ValueError('invalid_source_cutoff')
        return visible_observations(self.turns, cutoff_turn, parse_instant(now))

    def search_originals(self, question, *, now, cutoff_turn, limit=15):
        """Return lexical matches within the same history boundary as direct reads."""
        visible = self._search_scope(now, cutoff_turn, limit)
        return self._lexical_candidates(question, visible, limit)

    def _lexical_candidates(self, question, visible, limit):
        ranked = self._rank_sources(question, visible) if visible else []
        return {'matches': [index + 1 for index in ranked[:limit]],
                'visible_turns': len(visible), 'exhaustive': False}

    def search_phrases(self, question, *, now, cutoff_turn, limit=15):
        if self.phrase_index is None:
            raise ValueError('source_phrase_recall_disabled')
        visible = self._search_scope(now, cutoff_turn, limit)
        return self.phrase_index.search(question, visible, limit)

    def search_within_originals(self, question, turns, *, now, cutoff_turn, per_turn=2, include_next=False):
        """Select exact sentences within caller-selected turns, leaving turn order intact."""
        if (not isinstance(turns, (list, tuple)) or type(per_turn) is not int
                or not 1 <= per_turn <= 4 or len(turns) * per_turn > 32):
            raise ValueError('invalid_local_passage_limit')
        matches = []
        for turn in turns:
            source = self.read_original(turn, now=now, cutoff_turn=cutoff_turn)
            matches.extend(passage.receipt() for passage in rank_passages_in_turn(
                source, question, per_turn, include_next=include_next))
        return {'turns': list(turns), 'passages': matches, 'exhaustive': False}

    def read_citations(self, citations, *, now, cutoff_turn):
        """Read exact known citations without subjecting them to passage ranking."""
        if not isinstance(citations, (list, tuple)) or len(citations) > 32:
            raise ValueError('invalid_source_citations')
        sources, results = {}, {}
        for cite in citations:
            if not isinstance(cite, dict):
                raise ValueError('invalid_source_citations')
            turn, field, quote = (cite.get(key) for key in ('turn', 'field', 'quote'))
            if (type(turn) is not int or field not in ('user', 'assistant')
                    or not isinstance(quote, str) or not quote.strip()):
                raise ValueError('invalid_source_citations')
            if turn not in sources:
                sources[turn] = self.read_original(turn, now=now, cutoff_turn=cutoff_turn)
            text = sources[turn][field]
            start = text.find(quote)
            if start < 0:
                raise ValueError('source_citation_mismatch')
            unique = text.find(quote, start + 1) < 0
            results[(turn, field, quote)] = {'turn': turn, 'field': field, 'quote': quote,
                                            'start': start if unique else None,
                                            'end': start + len(quote) if unique else None}
        if sum(len(cite['quote']) for cite in results.values()) > 6400:
            raise ValueError('source_citation_budget_exceeded')
        return list(results.values())

    def commitment_candidates_for_sources(self, turns, *, now, cutoff_turn):
        """Use reviewed evidence links; a matching turn can refer to multiple events."""
        visible = self._search_scope(now, cutoff_turn, 15)
        if (not isinstance(turns, (list, tuple)) or len(turns) > 32
                or any(type(turn) is not int or turn - 1 not in visible for turn in turns)):
            raise ValueError('commitment_candidate_source_outside_visible_history')
        try:
            rows = reviewed_commitments_from_sources(
                self.csm, source_refs=[f'chat/{turn}' for turn in turns], now=now,
                source_until=max(visible.values(), default=parse_instant(now)).isoformat(),
                visible_source_ids={f'chat/{index + 1}' for index in visible},
            )
        except CSMError as error:
            if str(error) not in ('property_journal_not_initialized', 'entity_registry_not_initialized'):
                raise
            rows = []
        return {'resolution': 'pending_request_binding' if rows else 'no_reviewed_match', 'candidates': rows}

    def commitment_candidates_for_passages(self, passages, *, now, cutoff_turn):
        if (not isinstance(passages, (tuple, list)) or len(passages) > 32
                or any(not isinstance(passage, dict) for passage in passages)):
            raise ValueError('commitment_candidate_passages_invalid')
        for passage in passages:
            source = self.read_original(passage.get('turn'), now=now, cutoff_turn=cutoff_turn)
            verify_passage(passage, source)
        turns = list(dict.fromkeys(passage['turn'] for passage in passages))
        candidates = self.commitment_candidates_for_sources(turns, now=now, cutoff_turn=cutoff_turn)
        narrowed = narrow_passage_candidates(candidates['candidates'], passages)
        return {'resolution': 'pending_request_binding' if narrowed else 'no_reviewed_match', 'candidates': narrowed}

    def search_candidates(self, question, *, now, cutoff_turn, limit=15, distinct_passages=False):
        """Return independent passage and date candidates without publishing state."""
        if self.passage_index is None:
            raise ValueError('source_recall_lanes_disabled')
        visible = self._search_scope(now, cutoff_turn, limit)
        baseline = self._lexical_candidates(question, visible, limit)
        passages = []
        for passage in self.passage_index.search(question, visible, limit, distinct_passages=distinct_passages):
            original = self._source(passage.turn - 1)
            quote = original[passage.field][passage.start:passage.end]
            if quote != passage.text:
                raise ValueError('source_passage_mismatch')
            passages.append(passage.receipt())
        dates = [index + 1 for index in self.date_index.matching(now, cutoff_turn) if index in visible][:limit]
        return {**baseline, 'passages': passages, 'date_candidates': dates,
                'date_candidate_scope': 'calendar_match_only'}

    def _extra_passage_positions(self, question, visible, retained):
        return self._rank_sources(question, visible)[:16]

    def retrieve(self, question, now, cutoff_turn, item_id=None, *, _reviewed_state=(), **scope):
        direct_unbound = self.tail_start is None and not any(value is not None for value in scope.values())
        if direct_unbound and (self.recall_commitment_candidates or self.annotate_evidence_dates):
            keys = (candidate_scope(self, question, now=now, cutoff_turn=cutoff_turn)
                    if self.recall_commitment_candidates else ())
            result = self._retrieve(question, cutoff_turn, now=now, commitment_candidates=keys,
                                    annotate_evidence_dates=self.annotate_evidence_dates,
                                    reviewed_state=_reviewed_state)
        else:
            result = super().retrieve(question, now, cutoff_turn, item_id, _reviewed_state=_reviewed_state,
                                      **scope)
        # The natural-use board already has a policy for proactive memory.
        # This candidate adds passages only to direct, unbound requests.
        if not self.append_passages or not direct_unbound:
            return result
        budget = 6400
        heading = '【证据｜仅支撑】\n【聊天记录】'
        evidence = result.evidence or heading
        remaining = budget - len(result.state_text) - 2 - len(evidence)
        if remaining < 180:
            return result
        visible = visible_observations(self.turns, cutoff_turn, parse_instant(now))
        retained = set(result.used_turns)
        extra = []
        for index in self._extra_passage_positions(question, visible, retained):
            if index + 1 in retained:
                continue
            original = self._source(index)
            passage = source_passage(original, question, limit=min(600, remaining - 80))
            block = self._source_block(passage)
            if len(block) + 2 > remaining:
                continue
            evidence += '\n\n' + block
            remaining -= len(block) + 2
            extra.append(index + 1)
            if len(extra) == 2 or remaining < 180:
                break
        if not extra:
            return result
        enriched = StateRetrieval(result.state_items, result.state_text, evidence,
                                  sorted(retained | set(extra)))
        enriched.meta.update(result.meta, added_original_turns=extra)
        return enriched
