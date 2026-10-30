"""Existing batch gateway client. Public interface is run_batch."""


def run_batch(jobs, send, max_attempts=3):
    results = []
    for job in jobs:
        response = None
        for attempt in range(max_attempts):
            response = send(job, attempt)
            if response['status'] < 500:
                break
        results.append(dict(tenant=job['tenant'], id=job['id'], state='ok',
                            status=response['status'], value=response.get('value'), attempts=attempt))
    return results
