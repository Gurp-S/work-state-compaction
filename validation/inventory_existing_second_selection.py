"""Read-only inventory of recorded C2 work, not a continuation experiment."""
from contextlib import closing
from hashlib import sha256
from pathlib import Path
import argparse
import json
import sqlite3


ROOTS = [
    Path('D:/agent-task-runs/wsc-c1-columns-qualification-20261027-v1'),
    Path('D:/agent-task-runs/wsc-c1-columns-repeats-20261027-v1/R02'),
    Path('D:/agent-task-runs/wsc-c1-columns-repeats-20261027-v1/R03'),
]


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return sha256(encode(value).encode('utf-8')).hexdigest()


def inventory(root, pins):
    base = root / 'R01'
    def read(name):
        path = base / name
        raw = path.read_bytes()
        pins[str(path)] = sha256(raw).hexdigest()
        return json.loads(raw.decode('utf-8'))
    previous, current = [read(f'C{n}-continuation.json') for n in (1, 2)]
    request = read('C2-generation/request.json')
    trace = read('C2-tool-trace.json')
    phase = read('C2-selection/phase-outcome.json')
    path = base / 'state.db'
    before = sha256(path.read_bytes()).hexdigest()
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        views = []
        for continuation in (previous, current):
            value = json.loads(db.execute('SELECT data FROM views WHERE id=?',
                                         (continuation['view_id'],)).fetchone()[0])
            if digest(value['body']) != value['digest']:
                raise ValueError('view_digest_changed')
            views.append(value)
        sources = {}
        for seq, identity, raw, seal in db.execute('SELECT seq,id,data,digest FROM events ORDER BY seq'):
            if sha256(raw.encode('utf-8')).hexdigest() != seal:
                raise ValueError('source_digest_changed')
            sources[identity] = dict(seq=seq, **json.loads(raw))
        for continuation, view in zip((previous, current), views):
            binding = view['binding']
            prefix = [r for r in sources.values() if r['seq'] <= binding['cut']]
            if binding['cut'] != continuation['cut'] or digest(prefix) != binding['source_digest']:
                raise ValueError('previous_or_current_source_binding_changed')
        db.rollback()
    after = sha256(path.read_bytes()).hexdigest()
    if after != before:
        raise ValueError('source_database_changed_during_read')
    pins[str(path)] = before
    old, new = [v['body'] for v in views]
    selected = [{s['seq'] for s in body['sources']} for body in (old, new)]
    old_cut, new_cut = previous['cut'], current['cut']
    tail = [r['seq'] for r in sources.values() if old_cut < r['seq'] <= new_cut]
    by_seq = {r['seq']: r for r in sources.values()}
    material = request['material']
    table = material['events']
    if table.get('format') != 'wsc.cold_event_rows/1':
        raise ValueError('unsupported_recorded_event_representation')
    inline_ranges = {}
    for row in table['other_events']:
        event = row['event']
        text = ''.join(span['text'] for span in event['spans'])
        seq = event['seq']
        if text != by_seq[seq]['text']:
            raise ValueError('tail_spans_not_exact_full_source_text')
        inline_ranges.setdefault(seq, []).append((0, len(text), text))
    for excerpt in material['previous_excerpts']:
        if excerpt['basis'] != 'public_text':
            continue
        seq = int(excerpt['source_id'][1:])
        text = excerpt['text']
        if by_seq[seq]['text'][excerpt['start']:excerpt['end']] != text:
            raise ValueError('previous_excerpt_binding_changed')
        inline_ranges.setdefault(seq, []).append((excerpt['start'], excerpt['end'], text))
    calls = []
    for entry in trace:
        args, value = entry['arguments'], entry['output']
        record = dict(call_id=entry['call_id'], arguments=args,
                      result_bytes=len(encode(value).encode('utf-8')),
                      exact_returned_range_already_inline=None)
        if args['operation'] == 'read' and value.get('status') == 'ok':
            seq, offset, end, text = value['seq'], value['offset'], value['end'], value['text']
            if value['original_source_id'] != by_seq[seq]['id'] or by_seq[seq]['text'][offset:end] != text:
                raise ValueError('tool_return_not_exact_bound_source_range')
            record.update(seq=seq, returned_text_bytes=len(text.encode('utf-8')),
                          source_after_previous_cut=seq > old_cut,
                          exact_returned_range_already_inline=any(
                              start <= offset <= end <= stop and shown[offset-start:end-start] == text
                              for start, stop, shown in inline_ranges.get(seq, [])))
        calls.append(record)
    old_refs = [r['ref'] for r in old['understandings']]
    new_refs = [r['ref'] for r in new['understandings']]
    return dict(root=str(root), previous_cut=old_cut, current_cut=new_cut,
                selected_sources_before=sorted(selected[0]), selected_sources_after=sorted(selected[1]),
                retained_old_sources=sorted(selected[0] & selected[1]),
                removed_old_selected_sources=sorted(selected[0] - selected[1]),
                newly_selected_historical_sources=sorted(s for s in selected[1]-selected[0] if s <= old_cut),
                raw_tail_sources=tail, selected_tail_sources=sorted(s for s in selected[1] if s > old_cut),
                understanding_refs_before=old_refs, understanding_refs_after=new_refs,
                removed_understanding_refs=sorted(set(old_refs)-set(new_refs)),
                clues_before=len(old['clues']), clues_after=len(new['clues']),
                exact_unchanged_clues=sum(digest(c) in {digest(v) for v in new['clues']} for c in old['clues']),
                excerpt_keys_before=[r['key'] for r in old.get('excerpts', [])],
                excerpt_keys_after=[r['key'] for r in new.get('excerpts', [])],
                inline_full_tail_sources=sorted(s for s in inline_ranges if s > old_cut),
                calls=calls, responses=phase['receipts']['response_count'],
                recorded_total_tokens=phase['receipts']['all_usage']['total_tokens'],
                phase_seconds=phase['seconds'], source_database_unchanged=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    pins = {}
    rows = [inventory(root, pins) for root in ROOTS]
    pins[str(Path(__file__))] = sha256(Path(__file__).read_bytes()).hexdigest()
    result = dict(scope='Existing selections and tool outputs only; not a new compression or continuation run.',
                  runs=rows, input_sha256=pins,
                  exact_overlap_note='Source identity and character ranges only; not semantic correctness, usefulness, or an instruction to suppress reads.',
                  skip_C2_correctness=None, skip_C2_tokens=None, skip_C2_seconds=None)
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out/'inventory.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(rows, ensure_ascii=False))


if __name__ == '__main__':
    main()
