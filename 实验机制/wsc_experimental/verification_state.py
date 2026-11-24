"""Opt-in projection of host-captured, version-scoped verification receipts."""
from __future__ import annotations

from re import fullmatch

from wsc.contracts import digest as seal, require
from wsc.evidence import authorize


def _version(value):
    return isinstance(value, str) and fullmatch(r'[0-9a-f]{64}', value) is not None


def project_verification(core, snapshot, *, scope):
    """Project trusted host observations for one verification scope at a cut.

    A scope identifies the check and its complete input manifest, including
    relevant config and environment. The host supplies the manifest digests.
    """
    require(isinstance(scope, str) and bool(scope.strip()), 'invalid_verification_scope')
    events, _ = core.snapshot_content(snapshot)
    return project_verification_rows(events, scope=scope,
                                     access=lambda key: authorize(core.store, core.access, key))


def verification_observation(event):
    return (event['kind'] == 'observation' and 'verification_scope' in event['payload']
            and event['payload'].get('type') in ('input_manifest', 'verification_receipt'))


def project_verification_rows(events, *, scope, access):
    current = None
    receipts = []
    for event in events:
        if not verification_observation(event):
            continue
        payload = event['payload']
        if payload.get('verification_scope') != scope:
            continue
        access(event['id'])
        if payload.get('type') == 'input_manifest':
            current = {'source': event['id'], 'digest': payload.get('digest')}
            require(current['digest'] is None or _version(current['digest']), 'invalid_input_manifest')
            fingerprint = current['digest']
        elif payload.get('type') == 'verification_receipt':
            outcome = payload.get('outcome')
            tested = payload.get('tested_digest')
            require(outcome in ('passed', 'failed', 'incomplete', 'unknown'), 'invalid_verification_outcome')
            require(tested is None or _version(tested), 'invalid_input_manifest')
            fingerprint = tested
            receipts.append({'source': event['id'], 'outcome': outcome, 'tested_digest': tested})
        if 'manifest' in payload:
            manifest = payload['manifest']
            require(isinstance(manifest, dict) and manifest.get('scope') == scope
                    and seal(manifest) == fingerprint, 'verification_manifest_seal_mismatch')

    digest = current['digest'] if current else None
    for receipt in receipts:
        tested = receipt['tested_digest']
        receipt['applicability'] = ('unknown' if digest is None or tested is None else
                                    'current' if tested == digest else 'historical')
    outcomes = {row['outcome'] for row in receipts if row['applicability'] == 'current'}
    definitive = outcomes & {'passed', 'failed'}
    status = 'conflict' if len(definitive) == 2 else next(iter(definitive), 'unknown')
    return {'scope': scope, 'current_manifest': current, 'status': status, 'receipts': receipts}
