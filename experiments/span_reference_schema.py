"""Optional compact output shape; source membership remains a compiler check."""
from copy import deepcopy
import re

REFERENCE_PATTERN = r"^s[1-9][0-9]*:[0-9]+:[0-9]+:[0-9a-f]{64}$"


def compact_schema(enumerated):
    result = deepcopy(enumerated)
    field = result["properties"]["span_refs"]
    if "enum" not in field["items"] and field.get("maxItems") != 0:
        raise ValueError("span_schema_membership_not_enumerated")
    refs = field["items"].get("enum", [])
    if not isinstance(refs, list) or any(not isinstance(ref, str) or
            re.fullmatch(REFERENCE_PATTERN, ref) is None for ref in refs):
        raise ValueError("span_schema_reference_shape_unknown")
    field["items"] = {"type": "string", "pattern": REFERENCE_PATTERN}
    if not refs:
        field["maxItems"] = 0
    return result
