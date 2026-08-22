"""POST /run — run one strategy (B0, B1, or the LLM agent) over a corpus
split, or the adversarial suite, through the real gate and executor."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.security import safe_data_dir
from baselines.b0_blind_retry import BlindRetry
from baselines.b1_scheduled_retry import ScheduledRetry
from eval.harness import run_strategy
from eval.loaders import load_configs, load_split
from eval.metrics import full_report
from redteam.generator import run_redteam_suite

router = APIRouter()

_STRATEGIES = {
    "B0": BlindRetry,
    "B1": ScheduledRetry,
}


def _resolve_agent_strategy():
    from agent.orchestrator import AgentStrategy

    return AgentStrategy


class RunRequest(BaseModel):
    strategy: Literal["B0", "B1", "agent"]
    data_dir: str = "data/corpus"
    mode: Literal["corpus", "redteam"] = "corpus"
    n_replicates: int = 1


@router.post("/run")
def run(req: RunRequest):
    cfg = load_configs()

    if req.strategy == "agent":
        strategy_cls = _resolve_agent_strategy()
    elif req.strategy in _STRATEGIES:
        strategy_cls = _STRATEGIES[req.strategy]
    else:
        raise HTTPException(400, f"unknown strategy {req.strategy!r}")

    if req.mode == "redteam":
        result = run_redteam_suite(
            strategy_cls(), cfg["policy"], cfg["taxonomy"], n_replicates=req.n_replicates
        )
        return result

    data_dir = safe_data_dir(req.data_dir)
    try:
        events, ground_truths, customers = load_split(data_dir)
    except FileNotFoundError as e:
        raise HTTPException(404, f"corpus split not found at {req.data_dir!r}: {e}") from e

    result = run_strategy(
        strategy_cls(), events, ground_truths, customers, cfg["policy"], cfg["taxonomy"],
        seed=cfg["simulation"]["seed"],
    )
    return full_report(result, ground_truths, cfg["policy"], cfg["economics"])
