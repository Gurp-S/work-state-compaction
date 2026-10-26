"""Opt-in five tasks x three paired repetitions, using the bounded-worker scheduler.

Task stages are not repetitions. This module establishes registration/settlement
coverage, not actual native isolation, quality review or statistical significance.
"""
from copy import deepcopy
from pathlib import Path
from statistics import median

from native_evidence import digest, save
from native_repeated_pairs import schedule, run_workers, settle, summarize_cost
from native_task_checks import require


def paired_plan(matrix):
    require(matrix.get('kind') == 'native_wsc_task_matrix_v1', 'matrix_kind_invalid')
    tasks = matrix.get('tasks')
    require(isinstance(tasks, list) and len(tasks) == 5, 'matrix_requires_five_tasks')
    ids = set()
    for task in tasks:
        name = task.get('id')
        require(isinstance(name, str) and name.isidentifier() and name not in ids, 'matrix_task_id_invalid')
        ids.add(name)
        require(isinstance(task.get('pairs'), list) and len(task['pairs']) == 3,
                'matrix_requires_three_repetitions_per_task')
        require(len({p.get('id') for p in task['pairs']}) == 3
                and all(isinstance(p.get('id'), str) and p['id'].isidentifier() for p in task['pairs']),
                'matrix_repetition_id_invalid')
    pairs = []
    # Interleave task categories so one category is not tied to one time window.
    for repeat in range(3):
        for task in tasks:
            pair = task['pairs'][repeat]
            pairs.append(dict(id=task['id']+'/'+pair['id'], conditions=deepcopy(task.get('conditions')),
                              arms=deepcopy(pair.get('arms'))))
    plan = dict(kind='native_wsc_repeated_pairs_v1', parallel_pairs=matrix.get('parallel_pairs'),
                pairs=pairs, matrix_registration=deepcopy(matrix), matrix_sha256=digest(matrix))
    schedule(plan)  # Validate all 30 writable resource sets and ports before work.
    return plan


def settle_matrix(matrix, observations):
    plan = paired_plan(matrix)
    raw = settle(plan, observations)
    tasks = []
    metrics = ('total_tokens', 'output_tokens', 'uncached_input_tokens', 'seconds')
    for task in matrix['tasks']:
        ids = {task['id']+'/'+p['id'] for p in task['pairs']}
        pairs = [p for p in raw['pairs'] if p['id'] in ids]
        counts = {k: sum(p['verdict'] == k for p in pairs) for k in raw['quality_counts']}
        valid = len(pairs)-counts['incomplete']
        differences = {}
        for metric in metrics:
            values = [p['C_minus_B'][metric] for p in pairs if p['C_minus_B'] is not None]
            differences[metric] = dict(pairs=len(values), median=median(values) if values else None,
                                      min=min(values) if values else None, max=max(values) if values else None)
        tasks.append(dict(id=task['id'], registered_pairs=3, valid_task_pairs=valid,
            three_repetitions_met=valid == 3, pairs=pairs, quality_counts=counts,
            matched_success_resource_differences=differences,
            cost_by_arm={arm: summarize_cost([raw['arms'][pair_id+'/'+arm] for pair_id in sorted(ids)])
                         for arm in ('B','C')}))
    return dict(matrix_sha256=digest(matrix), registered_tasks=5, registered_pairs=15,
                registered_trajectories=30, tasks=tasks,
                all_tasks_have_three_valid_pairs=all(t['three_repetitions_met'] for t in tasks),
                total_valid_task_pairs=sum(t['valid_task_pairs'] for t in tasks),
                aggregate_cost_by_arm=raw['cost_by_arm'], arms=raw['arms'],
                statistical_significance='not_established', cash=None,
                scope='Per-task paired descriptions; stages are not repeats; no pooled overall winner')


def run_matrix(matrix, worker, destination):
    plan = paired_plan(matrix)
    observed = run_workers(plan, worker, destination)
    result = settle_matrix(matrix, observed['worker_observations'])
    save(Path(destination)/'matrix-result.json', result)
    return result
