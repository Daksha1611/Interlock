"""THE SIMULATOR's ground truth. Reads config/taxonomy.yaml's recovery
curves — the numbers no strategy (baseline or agent) is allowed to see.

Freeze this module's behavior before writing src/baselines/ or src/agent/.
Nothing here imports from agent/ or baselines/, and nothing in agent/ or
baselines/ may import this module (see tests/test_isolation.py).
"""

from __future__ import annotations

import math

import numpy as np
import yaml


def load_taxonomy(path: str = "config/taxonomy.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _curve_prob(curve: dict, hours: float) -> float:
    ctype = curve["type"]
    p = curve["params"]
    if ctype == "flat":
        return p["prob"]
    if ctype == "exp_decay_window":
        # peaks at peak_hours, decays exponentially afterward, floors at floor_prob
        if hours <= p["peak_hours"]:
            return p["peak_prob"]
        elapsed = hours - p["peak_hours"]
        decayed = p["floor_prob"] + (p["peak_prob"] - p["floor_prob"]) * math.exp(
            -elapsed / p["decay_hours"]
        )
        return max(decayed, p["floor_prob"])
    if ctype == "sigmoid_time":
        # rises with elapsed time toward peak_prob (salary-cycle shape)
        x = p["steepness"] * (hours - p["midpoint_hours"])
        sig = 1.0 / (1.0 + math.exp(-x))
        return p["floor_prob"] + (p["peak_prob"] - p["floor_prob"]) * sig
    raise ValueError(f"unknown curve type: {ctype}")


def retry_success_probability(
    taxonomy: dict, reason: str, hours_since_first_failure: float, contacted: bool = False
) -> float:
    """True probability a RETRY succeeds. This is the number the agent must
    never see — it only ever sees the outcome (success/fail), never the
    probability that produced it."""
    entry = taxonomy["reasons"][reason]
    base = _curve_prob(entry["recovery_curve"], max(hours_since_first_failure, 0.0))
    if contacted:
        base += entry.get("contact_lift", 0.0)
    return min(max(base, 0.0), 1.0)


def nudge_success_probability(taxonomy: dict, reason: str) -> float:
    """True probability a NUDGE (non-retry intervention) converts."""
    entry = taxonomy["reasons"][reason]
    return entry.get("nudge_recovery_prob", 0.0)


def resolve_retry(
    rng: np.random.Generator, taxonomy: dict, reason: str, hours_since_first_failure: float,
    contacted: bool = False,
) -> bool:
    p = retry_success_probability(taxonomy, reason, hours_since_first_failure, contacted)
    return bool(rng.random() < p)


def resolve_nudge(rng: np.random.Generator, taxonomy: dict, reason: str) -> bool:
    p = nudge_success_probability(taxonomy, reason)
    return bool(rng.random() < p)
