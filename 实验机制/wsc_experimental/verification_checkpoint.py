"""Opt-in checkpoint adapter for host observations of validation scope."""
import json

from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.contracts import encode, identifier, require
from .verification_state import project_verification_rows, verification_observation


class VerificationCheckpointAdapter(CodexCheckpointAdapter):
    def __init__(self, *, scopes, compact_history=False):
        self.scopes = tuple(dict.fromkeys(identifier(scope) for scope in scopes))
        require(0 < len(self.scopes) <= 8, 'invalid_verification_scopes')
        require(type(compact_history) is bool, 'invalid_verification_history_policy')
        self.compact_history = compact_history

    def capabilities(self):
        return {**super().capabilities(), 'adapter': 'verification_checkpoint_v1',
                'verification_scopes': list(self.scopes), 'compact_verification_history': self.compact_history}

    def render(self, body, sources, cut, locators, *, source_index, understanding_index):
        require(body is not None, 'verification_checkpoint_requires_view')
        selected = [row for row in body['sources'] if not verification_observation(row)]
        native = [row for row in sources if not verification_observation(row)]
        items = super().render({**body, 'sources': selected}, native, cut, locators,
                               source_index=source_index, understanding_index=understanding_index)
        facts = json.loads(items[0]['content'][0]['text'])
        public_refs = {row['id']: f"source:s{row['seq']}" for row in sources
                       if verification_observation(row) and isinstance(row['text'], str)}
        state = []
        for scope in self.scopes:
            projection = project_verification_rows(sources, scope=scope, access=locators.__getitem__)
            receipts = projection.pop('receipts')
            latest = {}
            archived_counts = {}
            for receipt in receipts:
                key = receipt['applicability'], receipt['outcome']
                if self.compact_history and key[0] != 'current':
                    counts = archived_counts.setdefault(key[0], {})
                    counts[key[1]] = counts.get(key[1], 0) + 1
                    continue
                latest[key] = {k: v for k, v in receipt.items() if k != 'tested_digest'}
                if receipt['source'] in public_refs:
                    latest[key]['reference'] = public_refs[receipt['source']]
            manifest = projection['current_manifest']
            if manifest is not None and manifest['source'] in public_refs:
                manifest['reference'] = public_refs[manifest['source']]
            scope_state = {**projection, 'receipt_count': len(receipts), 'latest_receipts': list(latest.values())}
            if archived_counts:
                scope_state['archived_receipt_counts'] = archived_counts
            state.append(scope_state)
        facts['verification_state'] = state
        items[0]['content'][0]['text'] = encode(facts)
        return items
