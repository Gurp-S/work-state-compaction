"""Apply separately verified immutable credits without changing original claims."""
from .campaign_allocation import KEYS, remaining


def credited_remaining(reference, claims, credits):
    by_id = {c['claim_sha256']: c['limits'] for c in claims}
    if len(by_id) != len(claims):
        raise ValueError('credit_duplicate_claim')
    base = remaining(reference, list(by_id.values()))
    seen = set()
    for credit in credits:
        key = credit['claim_sha256']
        if key not in by_id or key in seen:
            raise ValueError('credit_unknown_or_duplicate_claim')
        seen.add(key)
        released = credit['released']
        remaining(by_id[key], [released])  # Strict shape and nonnegative bounds.
        for name in KEYS:
            base[name] += released[name]
    remaining(reference, [base])
    return base
