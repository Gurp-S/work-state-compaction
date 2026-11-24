"""One mixed queue over scenarios/arms/repeats, so every arm in the final
comparison gets the same number of samples without serialising arm by arm.

Usage:
  python queue_runs.py --spec "long-40:v3r:5-8,long-40:v2f:4-8,long-40:native:3-8" --jobs 5
"""
from __future__ import annotations

import argparse
import threading
import time

import matrix


def parse_reps(text: str) -> list[int]:
    reps = []
    for part in text.split(','):
        if '-' in part:
            start, end = part.split('-')
            reps += list(range(int(start), int(end) + 1))
        elif part.strip():
            reps.append(int(part))
    return reps


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--spec', required=True)
    parser.add_argument('--jobs', type=int, default=5)
    args = parser.parse_args()
    jobs = []
    for spec in args.spec.split(','):
        scenario, arm, reps = spec.split(':')
        for rep in parse_reps(reps):
            jobs.append((scenario, arm, rep))
    lock = threading.Lock()
    queue = list(jobs)
    results = []

    def progress(message: str) -> None:
        with lock:
            print(message, flush=True)

    def worker() -> None:
        while True:
            with lock:
                if not queue:
                    return
                scenario, arm, rep = queue.pop(0)
            matrix.run_one(scenario, arm, rep, progress)
            metrics = matrix.analyze_run(scenario, arm, rep)
            if metrics is not None:
                with lock:
                    results.append(metrics)

    started = time.time()
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(min(args.jobs, len(jobs)))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    print(f'queue finished in {int(time.time() - started)}s; rows={len(results)}')


if __name__ == '__main__':
    main()
