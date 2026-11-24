"""Opt-in Bench 2.2 adapter for write-side CSM revisions."""
import json
import re

from csm_bench22 import CsmBench22, SourceStore, StateRetrieval
from csm_bench22_scope import visible_observations
from csm_bench22_revision_relevance import rank_revisions
from wsc.csm import CSM, Event
from wsc.csm.contracts import parse_instant
from wsc.csm.cem.flat_revision import FlatRevisionMemory, revision_interpreter
from wsc.csm.cem.state_extraction import render_items
from wsc.csm.cem.visible_state import visible_state_rows


class FlatRevisionBench22(CsmBench22):
    def __init__(self, gateway, *, focus_state=False, state_embedder=None):
        super().__init__(None)
        self.interpret = revision_interpreter(self._ask)
        self.writer = FlatRevisionMemory(self.csm, self.interpret)
        self.gateway = gateway
        self.focus_state = focus_state
        self.state_embedder = state_embedder
        self.state_vectors = {}
        self.prefix = None

    def _ask(self, prompt):
        schema, _, archived = prompt.partition('\n')
        payload = json.loads(archived)
        payload['source'] = {'text': payload['source']['user'], 'time': payload['source']['time'],
                             'speaker': payload['source']['speaker']}
        response = self.gateway.chat('deepseek-v4.1-flash', [
            {'role': 'system', 'content': schema},
            {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
        ], 'ingest', 'state-revision', temperature=0, max_tokens=768, thinking={'type': 'disabled'})
        choice, = response['choices']
        if choice['finish_reason'] != 'stop':
            raise ValueError('revision_extraction_unfinished')
        return choice['message']['content']

    def ingest(self, turn):
        if turn['turn'] != self.mark() + 1:
            raise ValueError('non_contiguous_turn')
        source = self._source_payload(turn)
        self.writer.consume(Event(f"chat/{turn['turn']}", 'chat', {**source, 'speaker': '用户'},
                                  observed_at=turn['time']))
        self._index_source(source)

    def begin_tail(self):
        super().begin_tail()
        self.prefix = self.store
        self.store = SourceStore()
        self.prefix.connection.backup(self.store.connection)
        self.csm = CSM(self.store)
        self.writer = FlatRevisionMemory(self.csm, self.interpret)

    def rewind(self, token):
        if self.prefix is None:
            raise ValueError('revision_rewind_requires_branch')
        super().rewind(token)
        self.store.connection.close()
        self.store, self.prefix = self.prefix, None
        self.csm = CSM(self.store)
        self.writer = FlatRevisionMemory(self.csm, self.interpret)

    def retrieve(self, question, now, cutoff_turn, item_id=None):
        visible = visible_observations(self.turns, cutoff_turn, parse_instant(now))
        titles = set(re.findall(r'《([^《》\n]+)》', question))
        with self.store.connect() as db:
            rows = visible_state_rows(db, question, source_until=now,
                                      visible_source_ids={f'chat/{index + 1}' for index in visible},
                                      limit=None if titles or self.focus_state or self.state_embedder else 12,
                                      include_unranked=self.state_embedder is not None)
        if titles:
            rows = [row for row in rows if titles.intersection(
                anchor.strip('《》') for anchor in [row['entity'], *row['contexts']])]
        if self.focus_state or self.state_embedder is not None:
            rows = rank_revisions(question, rows, embedder=self.state_embedder, vector_cache=self.state_vectors)
        items = [{'kind': 'CLOCK', 'now': now}]
        used = set()
        for row in rows:
            kind = row['classification']
            if kind == 'HISTORICAL':
                continue
            turns = sorted(int(ref.split('/')[1]) for ref in row['source_refs'])
            label = f"{row['entity']} / {row['slot']}"
            if row['contexts']:
                label += ' (' + ', '.join(row['contexts']) + ')'
            item = {'kind': kind, 'source_turns': turns, 'revision': row['revision'],
                    'text': f"[{kind}] {label} r{row['revision']} = {row['value']}"}
            if len(render_items([*items, item])) <= 4000:
                items.append(item)
                used.update(turns)
        if len(items) == 1:
            items.append({'kind': 'NO_CONFIRMED_STATE', 'reason': 'no_visible_revision',
                          'text': '[NO_CONFIRMED_STATE] 没有匹配的可见修订。'})
        state = render_items(items)
        blocks, spans, turns = [], [], []
        heading = '【证据｜仅支撑】\n【聊天记录】'
        remaining = 6400 - len(state) - 2 - len(heading)
        for turn in sorted(used):
            original = self._source(turn - 1)
            if not original['user']:
                continue
            block = self._source_block({**original, '_full': original, 'assistant': ''})
            if len(block) + 2 <= remaining:
                blocks.append(block)
                turns.append(turn)
                spans.append({'event_id': f'chat/{turn}', 'path': ['user'], 'quote': original['user']})
                remaining -= len(block) + 2
        evidence = '\n\n'.join([heading, *blocks]) if blocks else ''
        result = StateRetrieval(items, state, evidence, sorted(used))
        result.meta.update(evidence_turns=turns, evidence_spans=spans)
        return result
