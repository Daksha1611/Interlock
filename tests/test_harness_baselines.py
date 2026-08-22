"""End-to-end: run B0/B1 through the real gate+executor over the generated
corpus. Locks in the headline safety claim (§9: policy violations must be
zero) for the baselines, and proves every logged decision is replayable
offline (§5)."""

from __future__ import annotations

import pytest

from audit.replay import replay_run
from baselines.b0_blind_retry import BlindRetry
from baselines.b1_scheduled_retry import ScheduledRetry
from eval.harness import run_strategy
from eval.loaders import load_configs, load_split
from eval.metrics import full_report


@pytest.fixture(scope="module")
def corpus():
    return load_split("data/corpus")


@pytest.fixture(scope="module")
def cfg():
    return load_configs()


@pytest.mark.parametrize("strategy_cls", [BlindRetry, ScheduledRetry])
def test_baseline_run_has_zero_policy_violations(strategy_cls, corpus, cfg):
    events, ground_truths, customers = corpus
    result = run_strategy(
        strategy_cls(), events, ground_truths, customers, cfg["policy"], cfg["taxonomy"],
        seed=cfg["simulation"]["seed"],
    )
    report = full_report(result, ground_truths, cfg["policy"], cfg["economics"])
    assert report["safety"]["policy_violations"] == 0
    assert report["safety"]["dnc_breaches"] == 0
    assert report["safety"]["risk_block_retries"] == 0
    assert report["safety"]["mandate_cap_breaches"] == 0


@pytest.mark.parametrize("strategy_cls", [BlindRetry, ScheduledRetry])
def test_baseline_run_is_fully_replayable(strategy_cls, corpus, cfg):
    events, ground_truths, customers = corpus
    result = run_strategy(
        strategy_cls(), events, ground_truths, customers, cfg["policy"], cfg["taxonomy"],
        seed=cfg["simulation"]["seed"],
    )
    summary = replay_run(result["run_id"])
    assert summary["fully_replayable"], summary["mismatches"]
    assert summary["n_decisions"] > 0
