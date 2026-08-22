"""GET /runs/{run_id} — list every logged decision for a run."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from api.security import safe_id
from audit.trail import AuditTrail

router = APIRouter()


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    run_id = safe_id(run_id, "run_id")
    trail = AuditTrail(run_id)
    records = trail.load_all()
    if not records:
        raise HTTPException(404, f"no run found with id {run_id!r}")
    return {
        "run_id": run_id,
        "n_decisions": len(records),
        "decisions": [
            {
                "decision_id": r.decision_id,
                "order_id": r.order_id,
                "step": r.step,
                "proposed_action": r.proposed_action["action_type"],
                "disposition": r.disposition,
                "disposition_reason": r.disposition_reason,
                "money_delta": r.money_delta,
            }
            for r in records
        ],
    }


@router.get("/runs/{run_id}/{decision_id}")
def get_decision(run_id: str, decision_id: str):
    run_id = safe_id(run_id, "run_id")
    decision_id = safe_id(decision_id, "decision_id")
    trail = AuditTrail(run_id)
    record = trail.get(decision_id)
    if record is None:
        raise HTTPException(404, f"no decision {decision_id!r} in run {run_id!r}")
    return asdict(record)
