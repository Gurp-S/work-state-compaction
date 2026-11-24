"""Host-side capture for verification executed against a sealed input manifest."""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from wsc.contracts import Event, digest, encode, identifier, require
from .verification_state import _version


@dataclass(frozen=True)
class VerificationManifest:
    scope: str
    inputs: Mapping[str, str]
    execution: Mapping[str, str]

    def __post_init__(self):
        object.__setattr__(self, 'inputs', MappingProxyType(dict(self.inputs)))
        object.__setattr__(self, 'execution', MappingProxyType(dict(self.execution)))

    def fingerprint(self):
        return digest(self.record())

    def record(self):
        identifier(self.scope)
        require(bool(self.inputs) and all(isinstance(name, str) and name and _version(seal)
                    for name, seal in self.inputs.items()), 'invalid_verification_inputs')
        require(bool(self.execution) and all(isinstance(name, str) and name and isinstance(value, str) and value
                    for name, value in self.execution.items()), 'invalid_verification_execution')
        return {'scope': self.scope, 'inputs': dict(self.inputs), 'execution': dict(self.execution)}


def manifest_observation(source_id, manifest):
    record = manifest.record()
    return _observation(source_id, {'type': 'input_manifest',
                        'verification_scope': manifest.scope, 'digest': digest(record)}, record)


def invalidate_manifest(source_id, *, scope):
    """Record a known change when the host has no fresh complete manifest."""
    return _observation(source_id, {'type': 'input_manifest',
                        'verification_scope': identifier(scope), 'digest': None})


def verification_receipt(source_id, *, scope, outcome, executed_manifest=None):
    """Bind only a host attestation of the actual sealed run inputs."""
    identifier(scope)
    require(outcome in ('passed', 'failed', 'incomplete', 'unknown'), 'invalid_verification_outcome')
    if executed_manifest is not None:
        require(executed_manifest.scope == scope, 'verification_receipt_scope_mismatch')
    record = executed_manifest.record() if executed_manifest is not None else None
    return _observation(source_id, {'type': 'verification_receipt',
                        'verification_scope': scope, 'outcome': outcome,
                        'tested_digest': digest(record) if record is not None else None}, record)


def _observation(source_id, public, manifest=None):
    payload = public if manifest is None else {**public, 'manifest': manifest}
    return Event(identifier(source_id), 'observation', payload, text=encode(public))
