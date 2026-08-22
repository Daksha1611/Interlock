"""GET /audit/{run_id}/{decision_id} — replay one decision offline, without
an LLM call, and show that the gate's logged disposition reproduces
exactly. This is the endpoint the pitch's live demo hits (§5, §11)."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from api.security import safe_id
from audit.replay import replay_decision, replay_run

router = APIRouter()


@router.get("/audit/{run_id}/{decision_id}")
def replay_one(run_id: str, decision_id: str):
    run_id = safe_id(run_id, "run_id")
    decision_id = safe_id(decision_id, "decision_id")
    try:
        result = replay_decision(run_id, decision_id)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return {
        "decision_id": result.decision_id,
        "original_disposition": result.original_disposition,
        "original_reason": result.original_reason,
        "replayed_disposition": result.replayed_disposition,
        "replayed_reason": result.replayed_reason,
        "matches": result.matches,
        "rule_results": [asdict(r) for r in result.replayed_decision.rule_results],
        "logged_record": asdict(result.record),
    }


@router.get("/audit/{run_id}")
def replay_all(run_id: str):
    run_id = safe_id(run_id, "run_id")
    return replay_run(run_id)
