"""Shared retained-thread admission for explicit experiment member sets."""
from copy import deepcopy

from native_evidence import digest


class NativeGroupAdmission:
    def __init__(self, observations, *, members, label="native_group"):
        self.members = frozenset(members)
        if len(self.members) < 2 or set(observations) != self.members:
            raise ValueError(label + "_members_incomplete")
        if len({v["thread_id"] for v in observations.values()}) != len(self.members):
            raise ValueError(label + "_thread_identity_reused")
        if any(v["response_count"] != 0 for v in observations.values()):
            raise ValueError(label + "_already_spent")
        if len({digest(v["host"]) for v in observations.values()}) != 1:
            raise ValueError(label + "_host_drift_before_inference")
        if len({v["controls_sha256"] for v in observations.values()}) != 1:
            raise ValueError(label + "_control_drift")
        self.observations = deepcopy(observations)
        self.executed = set()

    def execute(self, member, observations, callback):
        if member not in self.members or member in self.executed:
            raise ValueError("native_phase_unregistered_or_repeated")
        if set(observations) != self.members:
            raise ValueError("native_group_members_incomplete")
        for name, expected in self.observations.items():
            current = observations[name]
            for field in ("thread_id", "rollout_path", "host", "controls_sha256", "prefix_sha256"):
                if current[field] != expected[field]:
                    raise ValueError("native_retained_thread_drift:" + name + ":" + field)
            if name not in self.executed and current["response_count"] != 0:
                raise ValueError("native_unregistered_inference:" + name)
        self.executed.add(member)
        return callback()
