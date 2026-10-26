"""Opt-in receipt references with explicit value and file-byte hash domains.

canonical_json_utf8_v1 is wsc.contracts.encode: sorted keys, compact separators,
ensure_ascii=False, allow_nan=False, encoded as UTF-8. File identity describes
one observed read, not a lock or a claim that the path cannot subsequently change.
"""
from hashlib import sha256
import json
from pathlib import Path

from wsc.contracts import digest, require


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'receipt_duplicate_key')
        result[key] = value
    return result


def receipt_reference(receipt, path):
    """Bind the supplied receipt value to a single strict UTF-8 file observation."""
    require(type(receipt) is dict, 'receipt_object_required')
    expected = digest(receipt)
    raw = Path(path).read_bytes()
    observed = json.loads(raw.decode('utf-8-sig', errors='strict'), object_pairs_hook=_unique_object)
    require(type(observed) is dict and digest(observed) == expected, 'receipt_value_mismatch')
    return {'receipt_path': str(path), 'receipt_sha256': expected,
            'receipt_sha256_basis': 'canonical_json_utf8_v1',
            'receipt_file_sha256': sha256(raw).hexdigest(),
            'receipt_file_sha256_basis': 'raw_file_bytes'}
