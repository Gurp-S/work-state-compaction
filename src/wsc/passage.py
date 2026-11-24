"""One deterministic natural-language passage shared by every model-facing view.

The model never receives source records, archive paths or hashes. It receives
control text, current ledger entries, an optional work state, mechanical
verification facts and a discovery index over the cold store.
"""
from __future__ import annotations

LABELS = {'constraint': 'Constraint', 'requirement': 'Requirement', 'decision': 'Decision',
          'verification': 'Verification', 'fact': 'Context'}
RANK = {'fact': 0, 'verification': 1, 'decision': 2, 'requirement': 3, 'constraint': 4}


def _sentences(ledger, blocked):
    active = [entry for entry in ledger if entry.get('status', 'active') == 'active'
              and not any(text in entry['text'] for text in blocked)]
    active.sort(key=lambda entry: (-RANK.get(entry.get('kind'), 0),
                                   entry.get('seq', 0), entry.get('id', '')))
    sentences, seen = [], set()
    for entry in active:
        # Rounds may re-derive one claim as a new entry; state it once.
        if entry['text'] in seen:
            continue
        seen.add(entry['text'])
        sentences.append(f"{LABELS.get(entry.get('kind'), 'Context')}: {entry['text'].rstrip('.')}.")
    return ' '.join(sentences)


def _state_text(state, blocked, skip=()):
    parts = []
    for key in ('done', 'open', 'next', 'unknown'):
        if key in skip:
            continue
        rows = [row for row in state.get(key, []) if not any(text in row for text in blocked)]
        if rows:
            parts.append(f"{key}: {'; '.join(rows).rstrip('.')}")
    return ('State: ' + '. '.join(parts) + '.') if parts else ''


def _next_text(state, blocked):
    """A recorded next action gets its own line, not a clause inside State."""
    rows = [row for row in state.get('next', []) if not any(text in row for text in blocked)]
    if not rows:
        return ''
    row = '; '.join(rows)
    suffix = ' (assistant-originated)'
    if row.rstrip().endswith(suffix):
        row = row.rstrip()[:-len(suffix)]
        return f'Next action (recorded by assistant): {row.rstrip(".")}.'
    return f'Next action (recorded): {row.rstrip(".")}.'


def _receipts_text(receipts, represented=()):
    sentences = []
    for receipt in list(receipts)[-4:]:
        # One relation, one sentence: the state line already carries the edit
        # and its check for this path.
        if any(receipt['path'] in row and f"#{receipt['check']}" in row
               for row in represented):
            continue
        if receipt.get('check') is None:
            sentences.append(f"{receipt['path']} was edited at #{receipt['edit']} "
                             "and no later check covers it.")
        else:
            sentence = (f"{receipt['path']} was edited at #{receipt['edit']}; the check at "
                        f"#{receipt['check']} ({receipt['command']}) reported: "
                        f"{receipt['result'].rstrip('.')}.")
            if receipt.get('stale'):
                sentence += ' A later edit to the same file is not covered by that check.'
            sentences.append(sentence)
    return ('Checks: ' + ' '.join(sentences)) if sentences else ''


def values_text(values, blocked=(), shown=None):
    """Engine-owned exact values, newest first; archived keys stay addressable."""
    ordered = list(reversed([row for row in values
                             if not any(text in row.get('text', '') for text in blocked)]))
    total = len(ordered)
    shown = total if shown is None else max(0, min(shown, total))
    lines = []
    for row in ordered[:shown]:
        extra = [term for term in row.get('terms', [])
                 if term.lower() not in row.get('label', '').lower()]
        extra = [term for term in extra
                 if not any(term != other and term.lower() in other.lower() for other in extra)]
        line = f"[{row['key']}] {row['label']}"
        if extra:
            line += ' | terms: ' + ', '.join(term[:32] for term in extra[:6])
        lines.append(line)
    if not lines:
        if total:
            keys = [row['key'] for row in ordered]
            listed = ', '.join(keys) if len(keys) <= 10 else f'{keys[0]}..{keys[-1]}'
            return f'Observed values archived: fetch {listed}.'
        return ''
    text = ('Observed values (fetch by key): ' + '; '.join(lines) + '.')
    if total > shown:
        keys = [row['key'] for row in ordered[shown:]]
        listed = ', '.join(keys) if len(keys) <= 10 else f'{keys[0]}..{keys[-1]}'
        text += f' {total - shown} older values archived: fetch {listed}.'
    return text


def index_text(index, blocked=(), dropped=0):
    rows = [row for row in index if not any(text in row.get('text', '') for text in blocked)]
    if not rows:
        return ''
    lines = []
    for row in rows:
        extra = [term for term in row.get('terms', []) if term.lower() not in row['label'].lower()]
        # A term already covered by a longer term in the same row adds no
        # discovery value; a value row keeps more terms because its literals
        # are exactly what the index exists to expose.
        extra = [term for term in extra
                 if not any(term != other and term.lower() in other.lower() for other in extra)]
        extra = extra[:6 if row.get('kind') == 'value' else 2]
        line = f"[{row['key']}] {row['label']}"
        if extra:
            line += ' | terms: ' + ', '.join(term[:32] for term in extra)
        lines.append(line)
    text = ('Evidence index (fetch by key): ' + '; '.join(lines) + '.')
    if dropped:
        text += f" {dropped} further sources are archived without an index slot."
    return text


def render(*, control, ledger, state=None, receipts=(), index=(), values=(),
           values_max=None, budget=32768, blocked=(), dropped=0, next_banner=False):
    """Compose the passage, trimming index, then oldest values, then entries."""
    control = list(dict.fromkeys(text for text in control if text))
    ledger = list(ledger)
    index = list(index)
    values = list(values)
    blocked = list(blocked)
    shown_values = len([row for row in values
                        if not any(text in row.get('text', '') for text in blocked)])
    if values_max is not None:
        shown_values = min(shown_values, max(0, values_max))
    control_text = ('User requirements, quoted verbatim: '
                    + ' '.join(f"\"{text}\"" for text in control) + '.') if control else ''

    def build():
        paragraphs = [paragraph for paragraph in (
            control_text,
            ('Ledger (current): ' + _sentences(ledger, blocked))
            if _sentences(ledger, blocked) else '',
            _next_text(state, blocked) if (state is not None and next_banner) else '',
            _state_text(state, blocked, {'next'} if next_banner else ())
            if state is not None else '',
            _receipts_text(receipts, [row for rows in (state or {}).values() for row in rows]),
            values_text(values, blocked, shown_values),
            index_text(index, blocked, dropped),
        ) if paragraph]
        return '\n\n'.join(paragraphs)

    text = build()
    while len(text.encode()) > budget and index:
        index.pop()
        text = build()
    while len(text.encode()) > budget and shown_values > 0:
        shown_values -= 1
        text = build()
    while len(text.encode()) > budget:
        active = [entry for entry in ledger if entry.get('status', 'active') == 'active']
        if len(active) <= 1:
            break
        _, worst = min((RANK.get(entry.get('kind'), 0), position)
                       for position, entry in enumerate(ledger)
                       if entry.get('status', 'active') == 'active')
        ledger.pop(worst)
        text = build()
    return text
