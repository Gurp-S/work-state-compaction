"""Resume contract: use the engine's value section, batch evidence fetches.

The text belongs to the engine because it describes what the engine guarantees:
an authoritative value section, addressable keys, and one final-action turn.
Value rules are only stated when the checkpoint actually carries a value
section; naming a section that is absent costs reasoning and teaches nothing.
"""
from __future__ import annotations

VALUE_RULES = [
    '- The "Observed values" section is authoritative: copy its exact values directly.',
    '- Do not read a file to recover a value. Fetch a key only when the value you need is not listed.',
]


def resume_contract(has_values: bool = True) -> str:
    lines = [
        'You are resuming a coding session. The state above is all you have.',
        'Return only JSON of this form:',
        '{"actions":[{"tool":"edit","file":"<path>","content":"<replacement text>"},'
        '{"tool":"run","command":"<command>"},{"tool":"read","file":"<path>"},'
        '{"tool":"fetch","key":"E<number>"}]}',
        'Rules:',
        '- Emit only the actions needed to continue now, in order; no prose, no fences.',
        '- File changes must use edit with the exact text to write; never modify files through a shell command.',
    ]
    if has_values:
        lines += VALUE_RULES
    lines += [
        '- If a fact must be recalled exactly but is not in the state, fetch its index key '
        'or read the file; do not guess.',
        '- If several keys are needed, list every fetch action in one turn.',
        '- If the state already covers the task, return the final actions in your first turn '
        'and do not fetch or read.',
        '- If quoted user text marks a value or target stale, never use it.',
    ]
    return '\n'.join(lines)


RESUME_CONTRACT_V2 = resume_contract(True)
