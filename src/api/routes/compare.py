"""GET /compare — B0 vs B1 (vs the agent, if requested) on the same corpus
split, same seed, same gate. The recovery table for the pitch (§6, §11.5)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.security import safe_data_dir
from baselines.b0_blind_retry import BlindRetry
from baselines.b1_scheduled_retry import ScheduledRetry
from eval.harness import run_strategy
from eval.loaders import load_configs, load_split
from eval.metrics import full_report

router = APIRouter()


@router.get("/compare")
def compare(
    data_dir: str = Query("data/corpus"),
    include_agent: bool = Query(False, description="also run the live LLM agent (costs API calls)"),
):
    cfg = load_configs()
    safe_dir = safe_data_dir(data_dir)
    try:
        events, ground_truths, customers = load_split(safe_dir)
    except FileNotFoundError as e:
        raise HTTPException(404, f"corpus split not found at {data_dir!r}: {e}") from e

    strategies = [BlindRetry(), ScheduledRetry()]
    if include_agent:
        from agent.orchestrator import AgentStrategy

        strategies.append(AgentStrategy())

    reports = []
    for strat in strategies:
        result = run_strategy(
            strat, events, ground_truths, customers, cfg["policy"], cfg["taxonomy"],
            seed=cfg["simulation"]["seed"],
        )
        reports.append(full_report(result, ground_truths, cfg["policy"], cfg["economics"]))
    return {"data_dir": data_dir, "reports": reports}
