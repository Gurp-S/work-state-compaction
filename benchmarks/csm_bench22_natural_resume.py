"""Checkpoint natural-board answers without changing the official judging format."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from tempfile import NamedTemporaryFile

from bench22 import natural
from bench22.systems import Gateway


def _sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _atomic_text(path, text):
    with NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                            dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def _dump(path, value):
    _atomic_text(path, json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n')


def _script(probe):
    return [probe['probe']] if probe['tier'] == 'A' else probe['script']


def _saved(path, expected):
    row = json.loads(path.read_bytes())
    if (any(row.get(key) != value for key, value in expected.items())
            or row.get('prompt_sha256') != _sha(row['prompt'])
            or row.get('answer_sha256') != _sha(row['answer'])
            or row.get('leak_turns_after_visible') != []
            or any(type(turn) is not int or not 1 <= turn <= expected['visible_until']
                   for turn in row['used_turns'])):
        raise ValueError(f'natural_resume_row_mismatch: {path.name}')
    return row


def run_probe(system, probe, receipts, answer):
    from csm_bench22_batch_runner import feed_prefix

    mark = system.mark()
    seq = probe['cutoff_turn']
    if mark != seq:
        raise ValueError('natural_resume_prefix_mismatch')
    system.begin_tail()
    results = []
    try:
        tail = [{**turn, 'turn': seq + offset} for offset, turn in enumerate(probe.get('tail') or (), 1)]
        feed_prefix(system, tail)
        seq += len(tail)
        for k, turn in enumerate(_script(probe)):
            path = receipts / f'{probe["id"]}.{k}.json'
            expected = {'id': probe['id'], 'k': k, 'persona': probe['persona'],
                        'cutoff_turn': probe['cutoff_turn'], 'visible_until': seq,
                        'user': turn['user'], 'time': turn['time'],
                        'prior_answers_sha256': _sha(''.join(row['answer_sha256'] for row in results))}
            if path.exists():
                row = _saved(path, expected)
            else:
                result = system.retrieve(turn['user'], turn['time'], seq, item_id=probe['id'])
                if any(type(n) is not int or not 1 <= n <= seq for n in result.used_turns):
                    raise ValueError(f'natural_resume_source_outside_prefix: {probe["id"]}#{k}')
                row = {**expected, 'prompt': result.prompt, 'used_turns': result.used_turns,
                       'leak_turns_after_visible': [], 'meta': result.meta,
                       'prompt_sha256': _sha(result.prompt)}
                answer(row)
                row['answer_sha256'] = _sha(row['answer'])
                _dump(path, row)
            results.append(row)
            if probe['tier'] != 'A':
                seq += 1
                system.ingest({**turn, 'turn': seq, 'assistant': row['answer']})
    finally:
        system.rewind(mark)
    return results


def run_natural(*, outdir, **options):
    outdir.mkdir(parents=True, exist_ok=True)
    lock = sqlite3.connect(outdir / 'natural-writer.sqlite3', timeout=0)
    try:
        lock.execute('BEGIN EXCLUSIVE')
        _run_natural(outdir=outdir, **options)
    finally:
        lock.close()


def _run_natural(*, release, outdir, run, system_name, gateway_url, workers, system_factory, seal,
                 boundaries=None):
    from csm_bench22_batch_runner import advance_prefix

    histories = natural.load_histories(str(release))
    probes, _ = natural.load_natural(str(release / 'natural'), 'dev')
    receipts = outdir / 'answer-receipts'
    manifest = outdir / 'natural-resume.json'
    completed = outdir / 'turns.jsonl'
    if manifest.exists():
        if json.loads(manifest.read_bytes()) != seal:
            raise ValueError('natural_resume_configuration_mismatch')
    else:
        if completed.exists() or (receipts.exists() and any(receipts.iterdir())):
            raise ValueError('natural_resume_unsealed_output')
        _dump(manifest, seal)
    receipts.mkdir(exist_ok=True)

    def per_persona(persona):
        gw = Gateway(gateway_url, run, f'{system_name}:{persona}:natural-dev')
        system = system_factory(gw)
        history = histories[persona]
        pos = 0
        finished = []
        for probe in sorted((p for p in probes if p['persona'] == persona),
                            key=lambda p: (p['cutoff_turn'], p['id'])):
            stop = probe['cutoff_turn']
            advance_prefix(system, history, pos, stop, boundaries[persona] if boundaries else ())
            pos = stop

            def answer(row):
                prompt = natural.answer_prompt(row['prompt'], row['time'], row['user'])
                response = gw.chat(natural.ANSWER_MODEL, [{'role': 'user', 'content': prompt}],
                                   'answer', f'{row["id"]}#{row["k"]}', temperature=0,
                                   max_tokens=500, thinking={'type': 'disabled'})
                usage = response['usage']
                row['answer'] = response['choices'][0]['message'].get('content') or ''
                row['prompt_tokens'] = usage['prompt_tokens']
                row['completion_tokens'] = usage['completion_tokens']
                row['mem_tokens'] = round(usage['prompt_tokens'] * len(row['prompt']) / max(1, len(prompt)), 1)

            finished.extend(run_probe(system, probe, receipts, answer))
            print(persona, 'probe', probe['id'], 'cutoff', stop, flush=True)
        return finished

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(histories)))) as pool:
        results = [row for group in pool.map(per_persona, sorted(histories)) for row in group]
    expected = {(probe['id'], k) for probe in probes for k in range(len(_script(probe)))}
    actual = {(row['id'], row['k']) for row in results}
    if actual != expected or len(results) != len(expected):
        raise ValueError('natural_resume_incomplete')
    data = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in results)
    if completed.exists():
        if completed.read_text(encoding='utf-8') != data:
            raise ValueError('natural_resume_published_output_mismatch')
    else:
        _atomic_text(completed, data)
