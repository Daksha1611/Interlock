"""Replay: given a run ID and a decision ID, reconstruct exactly why that
decision went the way it did — offline, without an LLM call. Rebuilds the
gate evaluation deterministically from the logged context. This is the
single best thing to show live in the pitch (§5, §11 of the spec).
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from audit.trail import AuditTrail, DecisionRecord
from domain.serde import action_from_dict, context_from_dict
from gate.enforcer import Gate, GateDecision


@dataclass(frozen=True)
class ReplayResult:
    decision_id: str
    original_disposition: str
    original_reason: str
    replayed_disposition: str
    replayed_reason: str
    matches: bool
    replayed_decision: GateDecision
    record: DecisionRecord


def replay_decision(
    run_id: str,
    decision_id: str,
    policy_path: str = "config/policy.yaml",
    runs_dir: str = "runs",
    policy: dict | None = None,
    record: DecisionRecord | None = None,
) -> ReplayResult:
    if record is None:
        trail = AuditTrail(run_id, runs_dir=runs_dir)
        record = trail.get(decision_id)
        if record is None:
            raise KeyError(f"no decision {decision_id!r} found in run {run_id!r}")

    if policy is None:
        with open(policy_path) as f:
            policy = yaml.safe_load(f)

    ctx = context_from_dict(record.context_snapshot)
    action = action_from_dict(record.proposed_action)

    gate = Gate(policy)
    replayed = gate.evaluate(action, ctx)

    return ReplayResult(
        decision_id=decision_id,
        original_disposition=record.disposition,
        original_reason=record.disposition_reason,
        replayed_disposition=replayed.outcome.value,
        replayed_reason=replayed.reason,
        matches=(replayed.outcome.value == record.disposition),
        replayed_decision=replayed,
        record=record,
    )


def replay_run(run_id: str, policy_path: str = "config/policy.yaml", runs_dir: str = "runs") -> dict:
    """Replay every decision in a run. Returns a summary — used to prove the
    whole run is reconstructible offline, not just one cherry-picked case."""
    trail = AuditTrail(run_id, runs_dir=runs_dir)
    records = trail.load_all()
    with open(policy_path) as f:
        policy = yaml.safe_load(f)
    mismatches = []
    for record in records:
        result = replay_decision(run_id, record.decision_id, policy=policy, record=record)
        if not result.matches:
            mismatches.append(result.decision_id)
    return {
        "run_id": run_id,
        "n_decisions": len(records),
        "n_matched": len(records) - len(mismatches),
        "mismatches": mismatches,
        "fully_replayable": len(mismatches) == 0,
    }
