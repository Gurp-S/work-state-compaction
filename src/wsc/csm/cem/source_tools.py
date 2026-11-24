"""Read-only, session-scoped handles for explicitly offered identity revisions."""
import copy
import json
from ..contracts import digest
from ..contracts import CSMError


TOOL_NAME = 'csm_read_source'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


class SourceToolSession:
    def __init__(self, service, primary, *, until=None, max_reads=2,
                 max_chars=4000, per_read_chars=2000):
        if not (1 <= max_reads <= 2 and 512 <= per_read_chars <= max_chars <= 4000):
            raise ValueError('source_tool_budget_invalid')
        if len(primary) > 60:
            raise ValueError('source_tool_candidate_limit')
        self.service, self.until = service, until
        self.max_reads, self.max_chars, self.per_read_chars = max_reads, max_chars, per_read_chars
        self.reads = self.used_chars = 0
        self.handles, self.bindings, self.reasons, self.seen = {}, [], [], set()
        self.primary = copy.deepcopy(primary)
        with service.store.connect() as db:
            for index, original in enumerate(primary):
                item = copy.deepcopy(original)
                reason, matches = 'revision_unavailable', []
                mid = item.get('memory_id')
                if item.get('pending_id') or item.get('record_type') == 'pending':
                    reason = 'pending_not_revision'
                elif item.get('record_type') == 'source_event':
                    reason = 'source_already_in_context'
                elif isinstance(mid, str) and 'value' in item:
                    for revision, data in db.execute('SELECT revision,data FROM revisions WHERE memory_id=?', (mid,)):
                        record = json.loads(data)
                        if 'revision' in item and (type(item['revision']) is not int or revision != item['revision']):
                            continue
                        if digest(record.get('value')) == digest(item['value']):
                            matches.append((revision, record.get('value')))
                    reason = 'revision_ambiguous' if len(matches) > 1 else reason
                if len(matches) == 1:
                    revision, value = matches[0]
                    handle = 'r' + str(index + 1)
                    self.handles[handle] = {'memory_id': mid, 'revision': revision,
                                            'expected_value': copy.deepcopy(value)}
                    self.bindings.append((handle, mid, revision)); self.reasons.append(None)
                else:
                    self.bindings.append(None); self.reasons.append(reason)

    def catalogue(self, rendered):
        packet = copy.deepcopy(json.loads(rendered))
        if isinstance(packet, list):
            packet = {'items': packet}
        rows = packet.get('items')
        if not isinstance(rows, list) or len(rows) < len(self.bindings):
            raise ValueError('source_tool_render_alignment_invalid')
        for index, binding in enumerate(self.bindings):
            row = rows[index]
            original = self.primary[index]
            if any(row.get(key) != original.get(key) for key in ('entity', 'slot')):
                raise ValueError('source_tool_render_alignment_invalid')
            if binding and digest(row.get('value')) != digest(original.get('value')):
                # Renderers may decorate dates. Such text is not an exact revision value.
                self.handles.pop(binding[0], None)
                binding = None
                self.reasons[index] = 'rendered_value_mismatch'
            if row.get('record_type') == 'source_event':
                continue
            if 'status' in row:
                row['identity_status'] = row.pop('status')
            if row.get('classification') not in (None, 'PENDING_BINDING'):
                row['identity_classification'] = row['classification']
            is_pending = (self.reasons[index] == 'pending_not_revision' or row.get('pending_id')
                          or row.get('record_type') == 'pending')
            row['classification'] = 'PENDING_BINDING' if is_pending else 'UNKNOWN'
            if is_pending:
                row['record_type'] = 'pending'
            row['confirmed'] = False
            if binding:
                handle, memory_id, revision = binding
                row.update({'source_handle': handle, 'memory_id': memory_id, 'revision': revision})
            else:
                row['source_handle_unavailable'] = self.reasons[index]
        packet.update({'source_tool_policy': 'offered-revision-source-v1',
                       'state_scope': 'identity_revision_candidates_not_world_confirmation',
                       'completeness': 'not_established'})
        return packet

    def definition(self):
        return {'type': 'function', 'function': {'name': TOOL_NAME,
            'description': 'Original source context for one listed identity revision handle. Returned observations retain source provenance.',
            'parameters': {'type': 'object', 'properties': {'handle': {
                'type': 'string', 'enum': list(self.handles)}},
                'required': ['handle'], 'additionalProperties': False}}}

    def execute(self, name, arguments):
        if self.reads >= self.max_reads:
            raise ValueError('source_tool_read_limit')
        self.reads += 1
        remaining = self.max_chars - self.used_chars
        cap = min(self.per_read_chars, remaining)
        result = None
        try:
            if name != TOOL_NAME:
                raise ValueError('source_tool_unknown_name')
            def unique(pairs):
                values = {}
                for key, value in pairs:
                    if key in values:
                        raise ValueError('source_tool_duplicate_argument')
                    values[key] = value
                return values
            args = json.loads(arguments, object_pairs_hook=unique)
            if not isinstance(args, dict) or set(args) != {'handle'} or not isinstance(args['handle'], str):
                raise ValueError('source_tool_arguments_invalid')
            handle = args['handle']
            if handle not in self.handles:
                raise ValueError('source_tool_handle_not_offered')
            selected = self.handles[handle]
            key = (selected['memory_id'], selected['revision'])
            if key in self.seen:
                raise ValueError('source_tool_source_already_returned')
            if cap - 128 < 512:
                raise ValueError('source_tool_character_budget')
            result = self.service.source_evidence(**selected, until=self.until, max_chars=cap - 128)
            self.seen.add(key)
            body = {'result': result, 'reads_remaining': self.max_reads - self.reads}
        except (CSMError, ValueError, TypeError) as error:
            code = str(error) if isinstance(error, (CSMError, ValueError)) else 'source_tool_arguments_invalid'
            if isinstance(error, json.JSONDecodeError):
                code = 'source_tool_arguments_invalid'
            body = {'error': code, 'reads_remaining': self.max_reads - self.reads}
        text = encoded(body)
        if len(text) > cap:
            raise ValueError('source_tool_character_budget')
        self.used_chars += len(text)
        return text
