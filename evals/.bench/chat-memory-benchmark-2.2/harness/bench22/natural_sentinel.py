# -*- coding: utf-8 -*-
"""Leak sentinel for the natural-use board: same canary test as 2.1 (runner.run_sentinel) on the board's own cutoffs."""
import argparse, os
from . import runner
from .release import load_histories
from .natural import load_natural, ROOT
from .systems import Gateway

ap = argparse.ArgumentParser()
ap.add_argument("--release", required=True); ap.add_argument("--natural", required=True); ap.add_argument("--system", required=True)
ap.add_argument("--run", required=True); ap.add_argument("--gateway", default="http://127.0.0.1:18878/v1")
ap.add_argument("--leaky", action="store_true"); ap.add_argument("--sentinel-n", type=int, default=12); ap.add_argument("--seed", type=int, default=20261109)
a = ap.parse_args()
probes, _ = load_natural(a.natural, "sealed")
items = [{"id": p["id"], "persona": p["persona"], "cutoff_turn": p["cutoff_turn"], "kind": "main",
          "question": p["probe"]["user"], "now": p["probe"]["time"]} for p in probes if p["tier"] == "A"]
hist = load_histories(a.release)
out = os.path.join(ROOT, "runs", "bench22", a.run, a.system, "natural-sentinel")
os.makedirs(out, exist_ok=True)
runner.run_sentinel(a, items, hist, out, Gateway(a.gateway, a.run, a.system))
