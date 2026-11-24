"""Execution-layer publication of source-scoped set claims.

No free model prose is published. Evidence comes from a host-bound database
snapshot, never an incoming completeness flag. Current projections establish
known source members only; no world-total capability is available.
"""
import copy
import json

from ..contracts import digest
from ..contracts import require, CSMError
from .property_projection import project

TOOL = 'publish_source_claim'
POLICY = 'source-scoped-claim-publication-v1'


class SourceClaimSession:
    def __init__(self, service, binding_key, *, max_chars=4000, max_members=15, publication_chars=4000):
        require(type(publication_chars) is int and publication_chars >= 512, 'claim_publication_budget_invalid')
        self.service, self.binding_key = service, binding_key
        self.max_chars, self.max_members, self.publication_chars = max_chars, max_members, publication_chars
        self._packet = project(service, binding_key, max_chars=max_chars, max_members=max_members)
        self._digest = digest(self._packet)
        self._members = {m['entity_ref']: m['label'] for m in self._packet['members']}
        require(len(self._members) == len(self._packet['members']), 'claim_projection_duplicate_member')
        require(self._packet['world_total'] is None and self._packet['completeness'] == 'not_established',
                'claim_projection_capability_unsupported')

    def context(self):
        return copy.deepcopy(self._packet)

    def definition(self):
        return {'type': 'function', 'function': {'name': TOOL,
            'description': 'Publication of a source-scoped set claim for the supplied projection. World-total evidence is not established.',
            'parameters': {'type': 'object', 'properties': {
                'projection_ref': {'type': 'string', 'enum': ['p1']},
                'scope': {'type': 'string', 'enum': ['source_known_members', 'unknown'],
                    'description': 'source_known_members is the complete offered set; unknown is an uncertainty statement.'},
                'member_refs': {'type': 'array', 'maxItems': len(self._members), 'uniqueItems': True,
                    'items': ({'type': 'string', 'enum': list(self._members)} if self._members else {'type': 'string'})},
                'world_total': {'type': 'null'}},
                'required': ['projection_ref', 'scope', 'member_refs', 'world_total'],
                'additionalProperties': False}}}

    def publish(self, arguments):
        require(isinstance(arguments, str) and len(arguments) <= 4096, 'claim_arguments_budget')
        def unique(pairs):
            out = {}
            for key, value in pairs:
                require(key not in out, 'claim_duplicate_key'); out[key] = value
            return out
        try:
            claim = json.loads(arguments, object_pairs_hook=unique)
        except json.JSONDecodeError:
            raise CSMError('claim_json_invalid') from None
        require(isinstance(claim, dict) and set(claim) ==
                {'projection_ref', 'scope', 'member_refs', 'world_total'}, 'claim_fields_invalid')
        require(claim['projection_ref'] == 'p1', 'claim_projection_not_offered')
        require(claim['world_total'] is None, 'claim_world_total_not_established')
        require(claim['scope'] in ('source_known_members', 'unknown'), 'claim_scope_not_available')
        refs = claim['member_refs']
        require(isinstance(refs, list) and len(refs) <= 15 and all(isinstance(r, str) for r in refs),
                'claim_member_refs_invalid')
        require(len(refs) == len(set(refs)), 'claim_duplicate_member')
        require(set(refs) <= set(self._members), 'claim_member_not_offered')
        if claim['scope'] == 'source_known_members':
            require(set(refs) == set(self._members), 'claim_offered_members_omitted')
        else:
            require(not refs, 'claim_unknown_with_members')
        fresh = project(self.service, self.binding_key, max_chars=self.max_chars, max_members=self.max_members)
        require(digest(fresh) == self._digest, 'claim_projection_stale')
        labels = [self._members[ref] for ref in refs]
        if claim['scope'] == 'unknown':
            answer = 'The complete total is not established by the supplied sources.'
        elif labels:
            answer = 'Known members in the supplied source projection: ' + json.dumps(labels, ensure_ascii=False) + '. '
            answer += 'The complete total is not established.'
        else:
            answer = 'The supplied projection offers no member entries. The complete total is not established.'
        if self._packet['omitted_members']:
            answer += ' Additional source members were omitted from this projection.'
        receipt = {'policy': POLICY, 'status': 'published', 'projection_digest': self._digest,
            'identity_revision': self._packet['identity_revision'], 'binding_key': self.binding_key,
            'claim': copy.deepcopy(claim), 'member_labels': labels, 'answer': answer,
            'source_event_refs': list(dict.fromkeys(s['event_id'] for s in self._packet['sources'])),
            'omitted_from_projection': self._packet['omitted_members'],
            'world_total': None, 'completeness': 'not_established', 'confirmed': False,
            'semantic_support': self._packet['semantic_support'],
            'publication_scope': 'offered_source_projection_not_world_confirmation'}
        require(len(json.dumps(receipt, ensure_ascii=False, separators=(',', ':'))) <= self.publication_chars,
                'claim_publication_budget')
        return receipt

    def publish_response(self, response):
        require(isinstance(response, dict), 'claim_response_invalid')
        choices = response.get('choices')
        require(isinstance(choices, list) and len(choices) == 1, 'claim_response_invalid')
        choice = choices[0]
        require(isinstance(choice, dict), 'claim_response_invalid')
        require(choice.get('finish_reason') == 'tool_calls', 'claim_tool_required')
        message = choice.get('message') or {}
        require(isinstance(message, dict), 'claim_response_invalid')
        calls = message.get('tool_calls')
        require(not message.get('function_call') and isinstance(calls, list) and len(calls) == 1,
                'claim_tool_batch_invalid')
        call = calls[0]
        require(isinstance(call, dict) and isinstance(call.get('function'), dict), 'claim_tool_batch_invalid')
        require(call.get('type') == 'function' and (call.get('function') or {}).get('name') == TOOL,
                'claim_tool_not_offered')
        require(isinstance(call.get('id'), str) and bool(call['id']), 'claim_tool_id_invalid')
        # Accompanying unvalidated content is diagnostic data, never part of answer.
        return self.publish(call['function'].get('arguments'))
