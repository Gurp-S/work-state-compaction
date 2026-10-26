"""Initial paired bootstrap gate, then fixed-host checks without peer wait bias."""
import json
from pathlib import Path
from threading import Condition
import time

from native_evidence import digest, read, save, state
from native_recursive_fork import metadata
from native_rollout_snapshot import parse_rollout
from native_host_controls import bootstrap_items


class PairedAdmission:
    def __init__(self, destination, timeout=600):
        self.destination = Path(destination)
        self.destination.mkdir(parents=True, exist_ok=False)
        self.timeout = timeout
        self.condition = Condition()
        self.initial, self.finished_states = {}, {}
        self.materialized_host = {}

    def after_first_phase(self, job, host_sources):
        workspace = str(Path(job['resources']['workspace']).resolve())
        content = json.dumps([dict(kind=v['kind'], content=v['content']) for v in host_sources], ensure_ascii=False, sort_keys=True)
        for spelling in (json.dumps(workspace)[1:-1], workspace, workspace.replace('\\','/')):
            content = content.replace(spelling, '$REGISTERED_WORKSPACE')
        pair = job['pair_id']
        with self.condition:
            self.materialized_host.setdefault(pair, {})[job['arm']] = content
            self.condition.notify_all()
            deadline = time.monotonic() + 720
            while len(self.materialized_host[pair]) < 2:
                self.check(job)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('paired_lazy_host_materialization_timeout')
                self.condition.wait(min(1, remaining))
            matched = self.materialized_host[pair]['B'] == self.materialized_host[pair]['C']
            save(self.destination / pair.replace('/', '_') / (job['arm'] + '-materialized-host.json'),
                 dict(matched=matched, normalized_content_sha256=digest(content)))
            if not matched:
                raise RuntimeError('paired_materialized_host_sources_differ')

    def check(self, job):
        with self.condition:
            peer = 'C' if job['arm'] == 'B' else 'B'
            if self.finished_states.get((job['pair_id'], peer)) == 'infrastructure_error':
                raise RuntimeError('paired_peer_infrastructure_failure')

    def finished(self, job, final_state):
        with self.condition:
            self.finished_states[(job['pair_id'], job['arm'])] = final_state
            self.condition.notify_all()

    def __call__(self, job, boundary, session):
        self.check(job)
        workspace = str(Path(session.registration['workspace']).resolve())
        def normalize(value):
            if isinstance(value, str):
                for spelling in (json.dumps(workspace)[1:-1], workspace, workspace.replace('\\','/')):
                    value = value.replace(spelling, '$REGISTERED_WORKSPACE')
                return value
            if isinstance(value, dict):
                return {k:normalize(v) for k,v in value.items()}
            if isinstance(value, list):
                return [normalize(v) for v in value]
            return value
        raw = (session.destination / 'opened.jsonl').read_bytes()
        rows = parse_rollout(raw).rows
        meta = metadata(rows)
        host = normalize(dict(configuration={key:session.opened.get(key) for key in (
            'model','modelProvider','reasoningEffort','cwd','sandbox','approvalPolicy','serviceTier','runtimeWorkspaceRoots')},
            base_instructions=meta.get('base_instructions'), dynamic_tools=meta.get('dynamic_tools')))
        pair = job['pair_id']
        artifact = self.destination / pair.replace('/', '_') / (job['arm'] + f'-{boundary}.json')
        if boundary == 0:
            items = bootstrap_items(state(rows), workspace)
            observation = dict(host=host, bootstrap_items=items, input_conditions=job['conditions_sha256'])
            with self.condition:
                self.initial.setdefault(pair, {})[job['arm']] = observation
                self.condition.notify_all()
                deadline = time.monotonic() + self.timeout
                while len(self.initial[pair]) < 2:
                    self.check(job)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('paired_initial_admission_timeout')
                    self.condition.wait(min(1, remaining))
                if self.initial[pair]['B'] != self.initial[pair]['C']:
                    save(artifact, dict(matched=False, observation=observation))
                    raise RuntimeError('paired_initial_host_or_bootstrap_differs')
            save(artifact, dict(matched=True, control_sha256=digest(observation), scope='Observed bootstrap/settings, not wire request proof'))
        else:
            expected = self.initial[pair][job['arm']]['host']
            matched = host == expected
            save(artifact, dict(matched=matched, actual_host=host, initial_host_sha256=digest(expected),
                scope='Same registered host controls; B/C context differences are the intervention'))
            if not matched:
                raise RuntimeError('paired_boundary_host_controls_changed')
