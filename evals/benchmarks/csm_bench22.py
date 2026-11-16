"""CSM source-memory adapter for the official Bench 2.2 System interface."""
from contextlib import contextmanager
import json
import re
import sqlite3

from bench22.systems import IncBM25, Retrieval, System

from wsc.contracts import digest
from wsc.csm import CSM, CsmStore, Event
from wsc.csm.contracts import parse_instant
from wsc.csm.state_bundle import build_state_bundle
from wsc.csm.state_extraction import StateProducerResponseError, merge_state_items, render_items
from wsc.csm.state_merge import coherent_producer_items
from wsc.csm.producer_binding import outside_pending_scope
from csm_bench22_state import CalendarEvidence, gateway_extractor
from csm_bench22_passages import source_passage
from csm_bench22_producer_budget import date_supplement, fit_answer_evidence
from csm_bench22_reviewed_evidence import fit_state_evidence
from csm_bench22_temporal_evidence import fit_deadline_appendix
from csm_bench22_neighbor_order import order_direct_with_neighbors
from csm_bench22_dialogue_links import attach_clarification
from csm_bench22_observation_comparison import group_observations
from csm_bench22_natural_carry import previous_user_query
from csm_bench22_contact_windows import contact_window_state
from csm_bench22_relative_scope import scope_relative_current
from csm_bench22_premise_scope import scope_numeric_premises
from csm_bench22_conflict_scope import scope_producer_conflicts, suppress_unresolved_current
from csm_bench22_negative_claims import scope_negative_claims
from csm_bench22_scope import rank_visible, visible_observations
from csm_bench22_source_scope import scope_source_accounts
from csm_bench22_temporal_scope import candidate_temporal_items, scope_temporal_items


class SourceStore(CsmStore):
    def __init__(self):
        self.connection = sqlite3.connect(':memory:', isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        super().__init__(':memory:', namespace='bench22')

    @contextmanager
    def connect(self):
        yield self.connection


class StateRetrieval(Retrieval):
    """Bench 2.2 retrieval with state and evidence as separate fields.

    The evaluator only reads ``prompt`` and ``used_turns``; the contract tests
    read ``state_items`` and ``evidence`` to prove that state is not just a
    string prefixed to a source dump.
    """

    def __init__(self, state_items, state_text, evidence_text, used_turns):
        if not state_items or not state_text:
            raise ValueError('state_required')
        if state_items[0]['kind'] != 'CLOCK' or len(state_items) < 2:
            raise ValueError('state_incomplete')
        if state_text != render_items(state_items):
            raise ValueError('state_render_mismatch')
        kinds = [item['kind'] for item in state_items]
        if 'NO_CONFIRMED_STATE' in kinds and (
            kinds != ['CLOCK', 'NO_CONFIRMED_STATE'] or not state_items[1].get('reason')
        ):
            raise ValueError('state_incomplete')
        if any(not item.get('source_turns') or not set(item['source_turns']) <= set(used_turns)
               for item in state_items if item['kind'] in ('CURRENT_CONFIRMED', 'DUE', 'DEADLINE_DATE', 'COMMITMENT_STATE', 'TEMPORAL_WINDOW',
                                                           'CONFLICT_UNRESOLVED', 'CONDITIONAL_RULE', 'SOURCE_ACCOUNT',
                                                           'OBSERVATION_COMPARISON')):
            raise ValueError('state_source_required')
        self.state_items = list(state_items)
        self.state_text = state_text
        self.evidence = evidence_text
        prompt = '\n\n'.join(part for part in (state_text, evidence_text) if part)
        super().__init__(prompt, used_turns, {'state_items': self.state_items})


class CsmBench22(System):
    name = 'csm-source'

    def __init__(self, gateway, state_extractor=None, *, produce_state=False, passage_evidence=False,
                 revision_state=False, scope_calendar_state=False, separate_producer_budget=False,
                 candidate_temporal_state=False, validate_conflict_sources=False, retain_off_day=False, store=None,
                 scope_relative_state=False, scope_numeric_state=False, scope_producer_source=False,
                 scope_negative_state=False, require_commitment_scope=False, link_clarifications=False,
                 link_previous_observations=False, group_observation_comparisons=False,
                 carry_natural_topic=False, scope_contact_windows=False):
        if produce_state and state_extractor is None:
            if gateway is None:
                raise ValueError('state_producer_required')
            state_extractor = gateway_extractor(gateway, retain_off_day=retain_off_day)
        self.store = SourceStore() if store is None else store
        self.csm = CSM(self.store)
        self.turns = []
        self.full_index = IncBM25()
        self.user_index = IncBM25()
        self.tail_start = None
        # Optional read-time state producer.  Without one the bundle still
        # publishes an explicit NO_CONFIRMED_STATE item; it never silently
        # degrades to evidence-only.
        self.state_extractor = state_extractor
        self.calendar_evidence = CalendarEvidence() if self.state_extractor is not None else None
        self.passage_evidence = passage_evidence
        self.revision_state = revision_state
        self.scope_calendar_state = scope_calendar_state
        self.separate_producer_budget = separate_producer_budget
        self.candidate_temporal_state = candidate_temporal_state
        self.validate_conflict_sources = validate_conflict_sources
        self.scope_relative_state = scope_relative_state
        self.scope_numeric_state = scope_numeric_state
        self.scope_producer_source = scope_producer_source
        self.scope_negative_state = scope_negative_state
        self.require_commitment_scope = require_commitment_scope
        self.link_clarifications = link_clarifications
        self.link_previous_observations = link_previous_observations
        self.group_observation_comparisons = group_observation_comparisons
        self.carry_natural_topic = carry_natural_topic
        self.scope_contact_windows = scope_contact_windows

    def ingest(self, turn):
        seq = turn['turn']
        if seq != len(self.turns) + 1:
            raise ValueError('non_contiguous_turn')
        source = self._source_payload(turn)
        self.csm.ingest([Event(f'chat/{seq}', 'chat', source, observed_at=source['time'])])
        self._index_source(source)

    def _index_source(self, source):
        self.turns.append(source)
        self.full_index.add(source['user'] + '\n' + source['assistant'])
        self.user_index.add(source['user'])
        if self.calendar_evidence is not None:
            self.calendar_evidence.add(source)

    def _source_payload(self, turn):
        return {key: turn[key] for key in ('turn', 'time', 'user', 'assistant')}

    def begin_tail(self):
        self.tail_start = self.mark()

    def rewind(self, token):
        if type(token) is not int or not 0 <= token <= len(self.turns):
            raise ValueError('invalid_rewind_mark')
        with self.store.transaction() as db:
            db.executemany('DELETE FROM events WHERE id=?',
                           ((f'chat/{t["turn"]}',) for t in self.turns[token:]))
        self.full_index.truncate(token)
        self.user_index.truncate(token)
        del self.turns[token:]
        if self.calendar_evidence is not None:
            self.calendar_evidence.rewind(token)
        self.tail_start = None

    def _source(self, index):
        source_id = f'chat/{index + 1}'
        with self.store.connect() as db:
            row = db.execute('SELECT data,digest FROM events WHERE id=?', (source_id,)).fetchone()
        source = json.loads(row['data'])
        if digest(source) != row['digest']:
            raise ValueError('source_digest_mismatch')
        return source

    @staticmethod
    def _source_block(source):
        label = ' | 原文片段' if source.get('_full') and (
            source['user'] != source['_full']['user'] or source['assistant'] != source['_full']['assistant']) else ''
        return f"[第{source['turn']}轮 | {source['time']}{label}]\n用户：{source['user']}\n助手：{source['assistant']}"

    def retrieve(self, question, now, cutoff_turn, item_id=None, *, commitment_binding=None,
                 commitment_owner=None, _reviewed_state=()):
        return self._retrieve(question, cutoff_turn, now=now, commitment_binding=commitment_binding,
                              commitment_owner=commitment_owner, reviewed_state=_reviewed_state)

    def _rank_sources(self, question, visible):
        return rank_visible(question, self.turns, visible, self.user_index, self.full_index)

    def _supplemental_sources(self, question, visible):
        return ()

    def _source_neighbors(self, ranked, visible):
        return [i + offset for i in ranked[:3] for offset in (-1, 1)
                if i + offset in visible
                and self.turns[i + offset]['time'][:10] == self.turns[i]['time'][:10]]

    def _retrieve(self, question, cutoff_turn, *, now, state_turns=(), use_producer=True,
                  commitment_binding=None, commitment_owner=None, commitment_candidates=(),
                  annotate_evidence_dates=False, prioritize_direct_sources=False,
                  protect_linked_neighbors=False, reviewed_state=()):
        if commitment_binding is not None and commitment_owner is not None:
            raise ValueError('commitment_scope_ambiguous')
        scoped_commitment = commitment_binding is not None or commitment_owner is not None
        extractor = self.state_extractor if use_producer and not scoped_commitment else None
        clock = parse_instant(now)
        stop = min(len(self.turns), cutoff_turn)
        if stop < 1:
            empty = [{'kind': 'CLOCK', 'now': now}, {
                      'kind': 'NO_CONFIRMED_STATE', 'text': '[NO_CONFIRMED_STATE] 无历史。',
                      'source_turns': (), 'reason': 'empty_history'}]
            return StateRetrieval(empty, render_items(empty), '', [])

        visible = visible_observations(self.turns, stop, clock)
        source_until = max(visible.values(), default=clock).isoformat()
        bundle = build_state_bundle(
            self.csm, now=now, source_until=source_until,
            visible_source_ids={f'chat/{index + 1}' for index in visible},
            question=question,
            revision_state=self.revision_state,
            commitment_binding=commitment_binding,
            commitment_owner=commitment_owner,
            include_unbound_commitments=not self.require_commitment_scope,
            commitment_candidates=commitment_candidates,
        )
        state_items = merge_state_items(bundle['items'], reviewed_state)
        state_text = render_items(state_items) if reviewed_state else bundle['text']
        state_turns = {turn for turn in state_turns if turn - 1 in visible} | set(bundle['turns'])

        natural = self.tail_start is not None
        observation_link = None
        recent = [] if scoped_commitment else list(visible)[-3:]
        ranked = [] if scoped_commitment else self._rank_sources(question, visible)
        if not scoped_commitment and natural:
            recent = [index for index in list(visible)[-5:] if index >= self.tail_start - 2]
            # Short acknowledgements carry little independent retrieval signal.
            words = re.sub(r'[^\w\u4e00-\u9fff]', '', question)
            ranked = ranked[:5] if len(words) >= 7 else []
            if self.carry_natural_topic:
                previous = previous_user_query(question, self.turns, visible, self.tail_start)
                if previous:
                    extras = [index for index in self._rank_sources(previous, visible)
                              if index < self.tail_start and index not in ranked]
                    ranked.extend(extras[:2])
        elif not scoped_commitment:
            # Include an adjacent exchange when a highly ranked turn depends on it.
            previous_candidates = ranked if self.link_previous_observations else ()
            neighbors = self._source_neighbors(ranked, visible)
            if protect_linked_neighbors:
                ranked = order_direct_with_neighbors(ranked, neighbors, self.turns)
            elif prioritize_direct_sources:
                ranked = ranked[:14] + neighbors
            else:
                ranked = ranked[:9] + neighbors + ranked[9:14]
            if self.link_clarifications:
                ranked, observation_link = attach_clarification(
                    ranked, self.turns, visible, previous_candidates=previous_candidates)
        budget = 3900 if natural else 6400
        supplemental = () if scoped_commitment else tuple(self._supplemental_sources(question, visible))
        calendar_only = set()
        separate_budget = extractor is not None and self.separate_producer_budget
        dates = []
        if extractor is not None:
            dates = [index for index in self.calendar_evidence.matching(now, stop) if index in visible][:5]
            if self.scope_calendar_state:
                request_sources = set(recent) | set(ranked) | set(supplemental)
                calendar_only = {index + 1 for index in dates if index not in request_sources} - state_turns
            if not separate_budget:
                ranked = dates + ranked
        ranked = [turn - 1 for turn in sorted(state_turns) if turn - 1 in visible] + ranked
        ranked.extend(supplemental)
        heading = '【证据｜仅支撑】\n【聊天记录】'
        state_reserve = max(1200, len(state_text)) if extractor is not None else len(state_text)
        selected = {}
        budget_overflow = {}
        visible_sources = {}
        used = len(heading) + (len(state_text) if separate_budget else state_reserve) + 2

        def read_source(index):
            source = self._source(index)
            if self.passage_evidence:
                source = source_passage(source, question)
            return source, self._source_block(source)

        for index in dict.fromkeys(reversed(recent)):
            if index not in visible:
                continue
            source, block = read_source(index)
            if used + len(block) + 2 <= budget // 2:
                selected[index] = block
                visible_sources[index + 1] = source
                used += len(block) + 2
        for index in ranked:
            if index in selected or index in budget_overflow or index not in visible:
                continue
            source, block = read_source(index)
            if used + len(block) + 2 <= budget:
                selected[index] = block
                visible_sources[index + 1] = source
                used += len(block) + 2
            elif reviewed_state:
                budget_overflow[index] = block
        if extractor is not None:
            extra = date_supplement(dates, visible_sources, read_source) if separate_budget else {}
            sources = dict(sorted({**visible_sources, **{i + 1: row[0] for i, row in extra.items()}}.items()))
            try:
                produced = extractor.extract(question, sources, now)
            except StateProducerResponseError as error:
                fallback = self._retrieve(question, cutoff_turn, now=now,
                                          state_turns=state_turns, use_producer=False,
                                          commitment_candidates=commitment_candidates,
                                          annotate_evidence_dates=annotate_evidence_dates,
                                          prioritize_direct_sources=prioritize_direct_sources,
                                          protect_linked_neighbors=protect_linked_neighbors,
                                          reviewed_state=reviewed_state)
                fallback.meta['state_producer_status'] = str(error)
                return fallback
            grounded = [item for item in produced
                        if item.get('source_turns') and set(item['source_turns']) <= sources.keys()]
            if self.candidate_temporal_state:
                grounded = candidate_temporal_items(grounded)
            elif calendar_only:
                grounded = scope_temporal_items(grounded, calendar_only)
            if self.scope_relative_state:
                grounded = scope_relative_current(grounded, sources, now)
            if self.scope_numeric_state:
                grounded = scope_numeric_premises(grounded, question)
            grounded = outside_pending_scope(grounded, bundle.get('pending_commitment_spans', ()), sources=sources)
            if self.validate_conflict_sources:
                grounded = suppress_unresolved_current(scope_producer_conflicts(grounded))
            coherent = coherent_producer_items(
                state_items, grounded, observation_sources=sources if self.scope_producer_source else None)
            if self.validate_conflict_sources:
                coherent = scope_producer_conflicts(coherent)
            for item in coherent:
                refs = set(item['source_turns'])
                merged = merge_state_items(state_items, [item])
                if len(render_items(merged)) <= state_reserve:
                    state_items = merged
                    state_turns.update(refs)
            if len(state_items) == 2 and state_items[1]['kind'] == 'NO_CONFIRMED_STATE':
                state_items[1] = {**state_items[1],
                    'reason': 'no_supported_producer_output' if sources else 'no_visible_evidence'}
            state_text = render_items(state_items)
            if separate_budget:
                selected = fit_answer_evidence(selected, extra, state_turns,
                                               allowance=budget - len(state_text) - len(heading) - 2)
        evidence_spans = None
        if any('source_spans' in item or any(cite['turn'] - 1 not in selected for cite in item.get('citations', ()))
               for item in state_items):
            state_items, state_text, selected, rejected, evidence_spans = fit_state_evidence(
                state_items, selected, read_original=self._source, source_block=self._source_block,
                visible=visible, budget=budget, heading=heading,
                retain_cited_exchange=bool(commitment_candidates or reviewed_state),
                overflow=budget_overflow)
            state_turns.difference_update(rejected)
        evidence_turns = [index + 1 for index in sorted(selected)]
        evidence = '\n\n'.join([heading, *(selected[t - 1] for t in evidence_turns)]) if evidence_turns else ''
        deadline_notes = []
        if annotate_evidence_dates and evidence:
            spare = budget - len(state_text) - len(evidence) - 2
            appendix, deadline_notes = fit_deadline_appendix(selected, read_source=self._source,
                                                             now=now, allowance=spare)
            evidence += appendix
        if self.scope_producer_source and extractor is not None:
            scoped = scope_source_accounts(state_items, sources)
            scoped_text = render_items(scoped)
            if len(scoped_text) + (2 + len(evidence) if evidence else 0) <= budget:
                state_items, state_text = scoped, scoped_text
        if self.scope_negative_state:
            scoped = scope_negative_claims(state_items)
            scoped_text = render_items(scoped)
            if len(scoped_text) + (2 + len(evidence) if evidence else 0) <= budget:
                state_items, state_text = scoped, scoped_text
        if self.group_observation_comparisons:
            grouped = group_observations(state_items, observation_link, evidence_turns)
            grouped_text = render_items(grouped)
            if len(grouped_text) + (2 + len(evidence) if evidence else 0) <= budget:
                state_items, state_text = grouped, grouped_text
        if self.scope_contact_windows:
            originals = (self._source(index) for index in selected)
            delivered = (source for source in originals if self._source_block(source) == selected[source['turn'] - 1])
            window = contact_window_state(question, now, delivered)
            if window is not None:
                scoped = merge_state_items(state_items, [window])
                scoped_text = render_items(scoped)
                if len(scoped_text) + (2 + len(evidence) if evidence else 0) <= budget:
                    state_items, state_text = scoped, scoped_text
        result = StateRetrieval(state_items, state_text, evidence, sorted(state_turns | set(evidence_turns)))
        if observation_link is not None:
            result.meta['observation_link'] = observation_link
        if separate_budget or evidence_spans is not None:
            result.meta['evidence_turns'] = evidence_turns
        if evidence_spans is not None:
            result.meta['evidence_spans'] = evidence_spans
        if annotate_evidence_dates:
            result.meta['deadline_annotations'] = deadline_notes
        return result
