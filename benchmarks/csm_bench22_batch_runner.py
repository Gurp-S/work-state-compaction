"""Write prefix batches at evaluation cutoffs, ahead of state retrieval."""
from hashlib import sha256
from pathlib import Path

from bench22 import natural, runner


BATCH_SIZE = 4


def feed_prefix(system, turns):
    ingest_batch = getattr(system, 'ingest_batch', None)
    if ingest_batch is None:
        for turn in turns:
            system.ingest(turn)
        return
    for start in range(0, len(turns), BATCH_SIZE):
        ingest_batch(turns[start:start + BATCH_SIZE])


def public_boundaries(release):
    root = Path(release)
    split = {row['id']: row['split'] for row in runner.jl(str(root / 'review-only/answer-key.jsonl'))}
    direct = (row for row in runner.load_items(str(root), with_key=False) if split[row['id']] == 'dev')
    natural_probes, _ = natural.load_natural(str(root / 'natural'), 'dev')
    boundaries = {}
    for row in (*direct, *natural_probes):
        boundaries.setdefault(row['persona'], set()).add(row['cutoff_turn'])
    return {persona: sorted(stops) for persona, stops in boundaries.items()}


def advance_prefix(system, history, start, stop, boundaries=()):
    for boundary in (*[point for point in boundaries if start < point < stop], stop):
        feed_prefix(system, history[start:boundary])
        start = boundary


def run_batch_persona(args, release, hist, persona, items, outdir, gw, sample_ids, *, boundaries):
    system = runner.REGISTRY[args.system](gw)
    path = Path(outdir) / 'contexts.jsonl'
    done = {row['id'] for row in runner.jl(str(path))} if path.exists() else set()
    todo = sorted((item for item in items if item['persona'] == persona
                   and (sample_ids is None or item['id'] in sample_ids)),
                  key=lambda item: (item['cutoff_turn'], item['id']))
    last = max((index for index, item in enumerate(todo) if item['id'] not in done), default=-1)
    gw.system = f'{args.system}:{persona}:{args.split}'
    previous = 0
    leaks = []
    for item in todo[:last + 1]:
        stop = item['cutoff_turn']
        advance_prefix(system, hist[persona], previous, stop, boundaries[persona])
        previous = stop
        if item['id'] in done:
            continue
        result = system.retrieve(item['question'], item['now'], stop, item_id=item['id'])
        outside = [turn for turn in result.used_turns if turn > stop]
        runner.append(str(path), {'id': item['id'], 'persona': persona, 'cutoff_turn': stop,
                      'used_turns': result.used_turns, 'meta': result.meta,
                      'leak_turns_after_cutoff': outside, 'prompt': result.prompt,
                      'prompt_sha256': sha256(result.prompt.encode('utf-8')).hexdigest()})
        if outside:
            leaks.append(item['id'])
    return leaks
