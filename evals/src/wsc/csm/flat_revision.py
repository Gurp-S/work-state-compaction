"""Write-time state interpretation over flat identities and the existing Revision store."""
import json

from . import identity, state
from .contracts import MemoryCandidate, identity_key, parse_instant, require, validate_candidate
from .retrieval import _terms
from .time_selection import as_of


def _source_text(payload):
    return str(payload.get('user', payload.get('text', ''))) if isinstance(payload, dict) else str(payload)


def _identity_choices(db, payload):
    source = ' '.join(_source_text(payload).lower().split())
    wanted = set(_terms(source))
    rows = db.execute(
        "SELECT i.memory_id, i.entity, i.slot, i.contexts "
        "FROM identities i JOIN heads h USING (memory_id) "
        "JOIN revisions r ON r.memory_id=h.memory_id AND r.revision=h.current_revision "
        "WHERE json_extract(i.data, '$.merged_into') IS NULL "
        "ORDER BY r.rowid DESC")
    candidates = [dict(row) for row in rows]
    candidates.sort(key=lambda row: (
        row['entity'].lower() in source,
        len(wanted.intersection(_terms(' '.join((row['entity'], row['slot'], row['contexts']))))),
    ), reverse=True)
    return [{key: row[key] for key in ('memory_id', 'entity', 'slot', 'contexts')} for row in candidates[:16]]


def revision_interpreter(ask):
    """Adapt one model call to write-time proposals. Entity choices are supplied in the request."""
    def interpret(event, candidates):
        text = json.dumps({'source': event.payload, 'entities': candidates}, ensure_ascii=False)
        schema = ('任务是把输入原文中可在后续使用的状态提炼为写入增量，包括明确的偏好、日期、对象属性、'
                  '重复出现的行为及触发条件、进度、承诺和变更。状态主题来自原文。'
                  '第一人称描述本人时，new_entity 可填写 "source.speaker" 指向输入指定的说话人。'
                  '已有同一实体、属性、范围时，target 使用候选 memory_id。'
                  '不同属性分别记录，保留原文给出的数值、单位和否定。纯寒暄或没有可用状态时返回空数组。'
                  '仅输出 JSON 数组。每项格式：'
                  '{"target":"one supplied memory ID or null","new_entity":"literal source label or null",'
                  '"slot":"attribute key","contexts":[],"value":null,"confidence":0.0}.')
        return json.loads(ask(schema + '\n' + text))
    return interpret


class FlatRevisionMemory:
    def __init__(self, csm, interpret):
        self.csm = csm
        self.interpret = interpret

    def consume(self, event, *, confirmed=False):
        self.csm.ingest([event])
        with self.csm.store.connect() as db:
            candidates = _identity_choices(db, event.payload)
        return self._write(event, self.interpret(event, candidates), candidates, confirmed=confirmed)

    def consume_batch(self, events, interpret_batch):
        events = tuple(events)
        require(1 <= len(events) <= 8, 'revision_batch_size')
        self.csm.ingest(events)
        combined = {'text': '\n'.join(_source_text(event.payload) for event in events)}
        with self.csm.store.connect() as db:
            candidates = _identity_choices(db, combined)
        grouped = interpret_batch(events, candidates)
        require(isinstance(grouped, dict), 'revision_batch_grouped_sources_required')
        require(set(grouped) <= {event.id for event in events}, 'revision_batch_source_unknown')
        return [self._write(event, grouped.get(event.id, ()), candidates) for event in events]

    def _write(self, event, proposals, candidates, *, confirmed=False):
        offered = {row['memory_id'] for row in candidates}
        speaker = event.payload.get('speaker') if isinstance(event.payload, dict) else None
        text = _source_text(event.payload)
        written = []
        with self.csm.store.transaction() as db:
            for proposal in proposals:
                target, confidence = proposal.get('target'), proposal['confidence']
                require(0 <= confidence <= 1, 'confidence_invalid')
                bound = target in offered and confidence > 0.6
                if bound:
                    owner = identity.identity_row(db, target)
                    require(not owner.get('merged_into'), 'identity_retired')
                    entity, slot, contexts = owner['entity'], owner['slot'], owner['contexts']
                else:
                    # The producer supplies an observed label for a new named identity.
                    entity = proposal.get('new_entity') if confidence > 0.6 else None
                    if entity == 'source.speaker':
                        entity = speaker
                    if entity and entity != speaker and entity not in text:
                        entity = None
                    entity = entity or f'temporary/{event.id}'
                    slot, contexts = proposal['slot'], proposal.get('contexts', ())
                data = validate_candidate(MemoryCandidate(
                    entity=entity, slot=slot, contexts=contexts, value=proposal['value'],
                    source_ids=(event.id,), valid_from=proposal.get('valid_from'), intent='create'))
                if (not confirmed or confidence <= 0.6 or entity.startswith('temporary/')
                        or (target is not None and not bound)):
                    data['certainty'] = 'SPECULATIVE'
                route = identity.route(db, data)
                recorded = self.csm.clock()
                if route['operation'] == 'CREATE':
                    owner = identity.create(db, data, producer='flat_revision', recorded_at=recorded)
                else:
                    owner = identity.identity_row(db, route['memory_id'])
                written.append(state.append(db, owner, data, producer='flat_revision', recorded_at=recorded,
                                            effective_at=event.observed_at, topics=[]))
        return written

    def read(self, entity, slot, contexts, *, now, visible_sources=None, history=False):
        key = identity_key(entity, slot, contexts)
        with self.csm.store.connect() as db:
            match = db.execute('SELECT memory_id FROM identities WHERE identity_key=?', (key,)).fetchone()
            if match is None:
                return []
            revisions = state.revisions(db, match['memory_id'])
        clock = parse_instant(now)
        visible = [row for row in revisions if row['effective_at'] and parse_instant(row['effective_at']) <= clock
                   and parse_instant(row['valid_from']) <= clock
                   and (visible_sources is None or set(row['source_refs']) <= visible_sources)]
        current = as_of(visible, now)
        if current is None:
            return []
        result = [{**current, 'classification': current.get('certainty', 'CURRENT_CONFIRMED')}]
        if history:
            result.extend({**row, 'classification': 'HISTORICAL'} for row in visible
                          if row['revision'] != current['revision'])
        return result

    def condition(self, entity, slot, contexts, *, expected, now, visible_sources=None):
        """Check a caller-declared prerequisite without changing the dependent state."""
        rows = self.read(entity, slot, contexts, now=now, visible_sources=visible_sources)
        if not rows or rows[0]['classification'] != 'CURRENT_CONFIRMED':
            return 'UNKNOWN'
        return 'READY' if rows[0]['value'] == expected else 'BLOCKED'
