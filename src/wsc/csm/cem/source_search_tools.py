"""Optional literal source search sharing the existing two-read/4000-char budget."""
import json
from ..contracts import CSMError

SEARCH = 'search_source_evidence'


class SourceSearchSession:
    def __init__(self, reader):
        self.reader = reader
        self.queries = set()

    def __getattr__(self, name):
        return getattr(self.reader, name)

    @property
    def can_offer(self):
        return True

    def catalogue(self, rendered):
        return {**self.reader.catalogue(rendered), 'source_search_available': True,
                'source_search_scope': 'literal_source_observations_not_world_confirmation'}

    def definitions(self):
        tools = [self.reader.definition()] if self.reader.handles else []
        tools.append({'type': 'function', 'function': {'name': SEARCH,
            'description': 'Literal matching observations from ingested source events within the current cutoff. Results retain original provenance and are not exhaustive.',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string', 'minLength': 1, 'maxLength': 300}},
                'required': ['query'], 'additionalProperties': False}}})
        return tools

    def execute(self, name, arguments):
        if name != SEARCH:
            return self.reader.execute(name, arguments)
        reader = self.reader
        if reader.reads >= reader.max_reads:
            raise ValueError('source_tool_read_limit')
        reader.reads += 1
        cap = min(reader.per_read_chars, reader.max_chars - reader.used_chars)
        try:
            def unique(pairs):
                out = {}
                for key, value in pairs:
                    if key in out: raise ValueError('source_search_duplicate_argument')
                    out[key] = value
                return out
            args = json.loads(arguments, object_pairs_hook=unique)
            if not isinstance(args, dict) or set(args) != {'query'} or not isinstance(args['query'], str):
                raise ValueError('source_search_arguments_invalid')
            query = args['query'].strip()
            if not query or len(query) > 300: raise ValueError('source_search_query_invalid')
            if query.casefold() in self.queries: raise ValueError('source_search_query_repeated')
            if cap - 128 < 512: raise ValueError('source_tool_character_budget')
            self.queries.add(query.casefold())
            packet = reader.service.recall_evidence(query, limit=3, max_chars=cap - 128,
                until=reader.until, record_types=('source_event',))
            body = {'result': packet, 'reads_remaining': reader.max_reads - reader.reads}
        except (CSMError, ValueError, TypeError) as error:
            code = str(error) if isinstance(error, (CSMError, ValueError)) else 'source_search_arguments_invalid'
            if isinstance(error, json.JSONDecodeError): code = 'source_search_arguments_invalid'
            body = {'error': code, 'reads_remaining': reader.max_reads - reader.reads}
        text = json.dumps(body, ensure_ascii=False, separators=(',', ':'))
        if len(text) > cap: raise ValueError('source_tool_character_budget')
        reader.used_chars += len(text)
        return text
