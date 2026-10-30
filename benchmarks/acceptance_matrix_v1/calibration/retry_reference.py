"""Calibration reference only; never copied into the model workspace."""
from copy import deepcopy
import json


def run_batch(jobs, send, max_attempts=3):
    if type(max_attempts) is not int or max_attempts < 1:
        raise ValueError('invalid_max_attempts')
    unique = {}
    for job in jobs:
        if (type(job) is not dict or any(type(job.get(k)) is not str or not job[k] for k in ('tenant', 'id'))
                or job.get('method') not in ('GET', 'POST')
                or (job['method'] == 'POST' and (type(job.get('idempotency_key')) is not str or not job['idempotency_key']))):
            raise ValueError('invalid_job')
        key = (job['tenant'], job['id'])
        wire = json.dumps(job, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if key in unique and unique[key][0] != wire:
            raise ValueError('job_identity_conflict')
        unique.setdefault(key, (wire, deepcopy(job)))
    results = []
    for _, job in unique.values():
        response = None
        for attempt in range(1, max_attempts+1):
            try:
                response = send(deepcopy(job), attempt)
            except TimeoutError:
                response = None
                if attempt < max_attempts:
                    continue
                break
            if response['status'] not in (429, 503) or attempt == max_attempts:
                break
        status = response['status'] if response is not None else None
        results.append(dict(tenant=job['tenant'], id=job['id'],
            state='ok' if status in (200, 201, 202, 204) else 'failed', status=status,
            value=response.get('value') if response is not None else None, attempts=attempt))
    return results
