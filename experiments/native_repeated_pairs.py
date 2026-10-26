"""Opt-in five-pair scheduling and descriptive settlement.

Workers must own their native processes, admission, cancellation and budgets.
This module schedules bounded workers; it does not establish native host
equivalence, enforce an in-flight token cap, or certify task quality itself.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from math import isfinite
from pathlib import Path
from statistics import median
from threading import Lock
import time

from native_evidence import FIELDS, digest, save
from native_continuity_checks import aggregate
from native_task_checks import require


def _sha256(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _overlaps(left, right):
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def summarize_cost(entries):
    """All registered trajectories count, including quality failures and unknowns."""
    known = {field: sum(e['usage']['known_usage'][field] for e in entries if e['usage']) for field in FIELDS}
    complete = bool(entries) and all(e['usage'] and e['usage']['complete'] for e in entries)
    quality_complete = bool(entries) and all(e['valid_task_observation'] for e in entries)
    successes = sum(e['quality'] == 'passed' for e in entries)
    return dict(known_usage=known, complete_usage=known if complete else None,
        complete=complete, successful_tasks=successes, quality_coverage_complete=quality_complete,
        tokens_per_success={k: v / successes for k, v in known.items()}
            if complete and quality_complete and successes else None,
        cash=None, scope='All registered trajectories, including failures; token counts, not currency')


def schedule(plan):
    require(plan.get('kind') == 'native_wsc_repeated_pairs_v1', 'repeated_plan_kind_invalid')
    pairs, parallel = plan.get('pairs'), plan.get('parallel_pairs')
    require(isinstance(pairs, list) and len(pairs) >= 5, 'repeated_minimum_five_pairs')
    require(type(parallel) is int and 1 < parallel <= len(pairs), 'repeated_parallel_pairs_invalid')
    ids, resources, ports, jobs = set(), [], set(), []
    for index, pair in enumerate(pairs):
        pair_id = pair.get('id')
        require(isinstance(pair_id, str) and pair_id and pair_id not in ids, 'repeated_pair_identity_invalid')
        ids.add(pair_id)
        conditions = pair.get('conditions')
        require(isinstance(conditions, dict) and all(conditions.get(k) for k in
            ('source_manifest_sha256', 'task_contract_sha256', 'model', 'effort', 'tools_sha256', 'budget')),
            'repeated_conditions_missing')
        require(all(_sha256(conditions[k]) for k in
                    ('source_manifest_sha256', 'task_contract_sha256', 'tools_sha256')),
                'repeated_condition_digest_invalid')
        require(set(pair.get('arms', {})) == {'B', 'C'}, 'repeated_arm_set_invalid')
        require(pair['arms']['B'].get('strategy') == 'native_control'
                and pair['arms']['C'].get('strategy') == 'registered_wsc', 'repeated_arm_meaning_invalid')
        order = ('B', 'C') if index % 2 == 0 else ('C', 'B')
        for arm in order:
            spec = pair['arms'][arm]
            roots = []
            for key in ('workspace', 'output', 'browser_profile'):
                path = Path(spec[key])
                require(path.is_absolute(), 'repeated_resource_not_absolute')
                resolved = path.resolve()
                require(not any(_overlaps(resolved, p) for p in resources + roots),
                        'repeated_writable_resource_overlap')
                roots.append(resolved)
            resources.extend(roots)
            require(isinstance(spec.get('ports'), list) and spec['ports'], 'repeated_ports_missing')
            for port in spec['ports']:
                require(type(port) is int and 1024 <= port <= 65535 and port not in ports,
                        'repeated_port_overlap_or_invalid')
                ports.add(port)
            jobs.append({'pair_id': pair_id, 'arm': arm, 'wave': index // parallel,
                         'conditions_sha256': digest(conditions), 'conditions': deepcopy(conditions),
                         'resources': deepcopy(spec)})
    return jobs


def run_workers(plan, worker, destination, *, waves=None):
    """Run all registered workers once, retaining peers when one worker fails.

    worker(job, record_phase) owns actual native checks/process handles and must
    return after its registered bounds. It journals each completed phase before
    starting the next, and returns the identical ordered phase list. On failure,
    known receipts survive but unobserved in-flight cost remains unknown. This
    is exception recovery, not process-crash recovery or timeout enforcement.
    """
    frozen = deepcopy(plan)
    jobs = schedule(frozen)  # Reject overlapping resources before any worker starts.
    available_waves = sorted({job['wave'] for job in jobs})
    selected_waves = available_waves if waves is None else waves
    require(isinstance(selected_waves, list) and selected_waves and
            all(type(n) is int and n in available_waves for n in selected_waves) and
            selected_waves == sorted(set(selected_waves)), 'repeated_selected_waves_invalid')
    destination = Path(destination)
    resolved = destination.resolve()
    require(not any(_overlaps(resolved, Path(job['resources'][key]).resolve())
                    for job in jobs for key in ('workspace', 'output', 'browser_profile')),
            'repeated_destination_overlap')
    destination.mkdir(parents=True, exist_ok=False)
    save(destination / 'registration.json', frozen)
    save(destination / 'wave-selection.json', dict(selected_waves=selected_waves, available_waves=available_waves))
    outcomes, started = {}, time.monotonic()
    for wave in selected_waves:
        group = [job for job in jobs if job['wave'] == wave]
        wave_start = time.monotonic()

        def invoke(job):
            begin = time.monotonic()
            phases, phase_lock = [], Lock()
            ordinal = jobs.index(job)

            def record_phase(phase):
                with phase_lock:
                    value = deepcopy(phase)
                    require(isinstance(value, dict), 'repeated_phase_invalid')
                    save(destination / 'phases' / f'{ordinal:03d}' / f'{len(phases):03d}.json', value)
                    phases.append(value)

            try:
                result = worker(deepcopy(job), record_phase)
                require(isinstance(result, dict), 'repeated_worker_result_invalid')
                require(result.get('phases') == phases, 'repeated_phase_journal_mismatch')
                # The scheduler identity never comes from mutable worker output.
                return {'job': job, 'result': result, 'worker_error': None,
                        'started_after_wave_seconds': begin - wave_start, 'wall_seconds': time.monotonic() - begin}
            except Exception as exc:
                return {'job': job, 'result': {'state': 'infrastructure_error', 'phases': deepcopy(phases)},
                        'worker_error': type(exc).__name__ + ':' + str(exc),
                        'started_after_wave_seconds': begin - wave_start, 'wall_seconds': time.monotonic() - begin}

        with ThreadPoolExecutor(max_workers=len(group), thread_name_prefix='native-study') as workers:
            futures = {workers.submit(invoke, job): job for job in group}
            for future in as_completed(futures):
                job = futures[future]
                observed = future.result()
                key = job['pair_id'] + '/' + job['arm']
                # Filenames use registered ordinals, not arbitrary pair IDs.
                ordinal = jobs.index(job)
                save(destination / 'workers' / f'{ordinal:03d}.json', observed)
                outcomes[key] = observed
    result = {'plan_sha256': digest(frozen), 'worker_observations': outcomes,
              'wall_seconds': time.monotonic() - started, 'automatic_retries': 0,
              'selected_waves': selected_waves,
              'unexecuted_registered_jobs': [j['pair_id']+'/'+j['arm'] for j in jobs if j['wave'] not in selected_waves],
              'scope': 'Bounded worker scheduling, not native task qualification'}
    save(destination / 'worker-result.json', result)
    return result


def settle(plan, observations):
    """Keep quality coverage separate from completeness of resource accounting.

    A worker's quality is a reviewed verdict with an evidence binding supplied
    by the task adapter. This function does not turn a self-report into a review.
    """
    jobs = schedule(plan)
    expected = {j['pair_id'] + '/' + j['arm']: j for j in jobs}
    require(set(observations) <= set(expected), 'repeated_unregistered_observation')
    arms, response_owner = {}, {}
    for key, job in expected.items():
        observed = observations.get(key)
        result = observed.get('result') if isinstance(observed, dict) else None
        entry = {'valid_task_observation': False, 'quality': 'unknown', 'usage': None,
                 'seconds': None, 'reason': 'missing_or_failed_worker'}
        arms[key] = entry
        if not isinstance(result, dict):
            continue
        require(observed['job'] == job, 'repeated_observed_job_changed')
        phases = result.get('phases', [])
        require(isinstance(phases, list), 'repeated_phases_invalid')
        require(all(isinstance(p, dict) and type(p.get('seconds')) in (int, float)
                    and isfinite(p['seconds']) and p['seconds'] >= 0 for p in phases),
                'repeated_phase_seconds_invalid')
        measured = aggregate(phases) if phases else None
        interrupted = bool(observed.get('worker_error')) or result.get('state') == 'infrastructure_error'
        if measured and interrupted:
            measured.update(complete=False, complete_usage=None)
        entry['usage'] = measured
        if measured:
            for rid in measured['response_ids']:
                require(rid not in response_owner, 'repeated_response_shared_between_arms')
                response_owner[rid] = key
        entry['seconds'] = sum(p['seconds'] for p in phases) if phases else None
        entry['seconds_complete'] = bool(phases) and not interrupted
        state, quality = result.get('state'), result.get('quality', {})
        quality_status = quality.get('status') if isinstance(quality, dict) else None
        valid = (bool(phases) and not interrupted
                 and result.get('conditions_sha256') == job['conditions_sha256']
                 and result.get('admission_matched') is True
                 and state in {'completed', 'task_failed', 'budget_exhausted'}
                 and quality_status in {'passed', 'failed'} and _sha256(quality.get('evidence_sha256'))
                 and (state == 'completed' or quality_status == 'failed'))
        entry.update(valid_task_observation=valid, quality=quality_status if valid else 'unknown',
                     reason=None if valid else 'admission_or_quality_not_established', state=state)
    pairs, differences = [], {k: [] for k in ('total_tokens', 'output_tokens', 'uncached_input_tokens', 'seconds')}
    counts = dict.fromkeys(('both_passed', 'B_only_passed', 'C_only_passed', 'both_failed', 'incomplete'), 0)
    for pair in plan['pairs']:
        b, c = (arms[pair['id'] + '/' + arm] for arm in ('B', 'C'))
        valid = b['valid_task_observation'] and c['valid_task_observation']
        verdict = ('both_passed' if b['quality'] == c['quality'] == 'passed' else
                   'B_only_passed' if b['quality'] == 'passed' else
                   'C_only_passed' if c['quality'] == 'passed' else 'both_failed') if valid else 'incomplete'
        counts[verdict] += 1
        delta = None
        # Compare resource differences only at matched successful quality with complete ledgers.
        if verdict == 'both_passed' and all(v['usage'] and v['usage']['complete'] for v in (b, c)):
            bu, cu = b['usage']['complete_usage'], c['usage']['complete_usage']
            delta = {'total_tokens': cu['total_tokens'] - bu['total_tokens'],
                     'output_tokens': cu['output_tokens'] - bu['output_tokens'],
                     'uncached_input_tokens': cu['input_tokens'] - cu['cached_input_tokens']
                                             - bu['input_tokens'] + bu['cached_input_tokens'],
                     'seconds': c['seconds'] - b['seconds']}
            for metric, value in delta.items():
                differences[metric].append(value)
        pairs.append({'id': pair['id'], 'verdict': verdict, 'C_minus_B': delta})
    valid_pairs = len(pairs) - counts['incomplete']
    cost_by_arm = {}
    for arm in ('B', 'C'):
        entries = [arms[pair['id'] + '/' + arm] for pair in plan['pairs']]
        cost_by_arm[arm] = summarize_cost(entries)
    return {'registered_pairs': len(pairs), 'valid_task_pairs': valid_pairs,
            'minimum_five_met': valid_pairs >= 5, 'pairs': pairs, 'quality_counts': counts, 'arms': arms,
            'cost_by_arm': cost_by_arm,
            'matched_success_resource_differences': {key: {'pairs': len(values),
                'median': median(values) if values else None, 'min': min(values) if values else None,
                'max': max(values) if values else None} for key, values in differences.items()},
            'cash': None, 'statistical_significance': 'not_established',
            'scope': 'Descriptive paired observations; task adapter owns evidence verification'}
