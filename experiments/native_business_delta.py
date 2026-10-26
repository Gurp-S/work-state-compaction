"""Separate producer-declared host skills from actual business-stage sources.

Only exact native metadata declarations are recognized. User text containing
similar tags remains a user source. Original native archives stay untouched.
"""
from native_evidence import digest


def split(rows):
    business, host = [], []
    for row in rows:
        if row['type'] != 'response_item':
            continue
        item = row['payload']
        meta = item.get('internal_chat_message_metadata_passthrough') or {}
        if not isinstance(meta, dict):
            meta = {}
        kinds = meta.get('content_item_kinds')
        origins = meta.get('content_item_metadata')
        declared = (item.get('type') == 'message' and item.get('role') == 'developer'
            and kinds == ['host_skills.instructions'] and isinstance(origins, list) and len(origins) == 1
            and isinstance(origins[0], dict)
            and origins[0].get('provenance') == {'type': 'skills'})
        if declared:
            host.append(dict(kind='host_skills.instructions', content=item['content'], source_item_sha256=digest(item)))
        else:
            business.append(row)
    return business, host
