"""Locks in proof requirement #1 (spec §1): zero policy violations across
the full adversarial suite — structurally, not statistically. Run here
against the deterministic baselines (free, no network); the live agent gets
the same suite via `python -m redteam.generator`, which needs
OPENROUTER_API_KEY and isn't part of this offline test suite.
"""

from __future__ import annotations

import pytest

from baselines.b0_blind_retry import BlindRetry
from baselines.b1_scheduled_retry import ScheduledRetry
from eval.loaders import load_configs
from redteam.generator import run_redteam_suite
from redteam.scenarios import ALL_SCENARIOS


@pytest.fixture(scope="module")
def cfg():
    return load_configs()


@pytest.mark.parametrize("strategy_cls", [BlindRetry, ScheduledRetry])
def test_redteam_suite_has_zero_system_violations(strategy_cls, cfg):
    result = run_redteam_suite(strategy_cls(), cfg["policy"], cfg["taxonomy"], n_replicates=1)
    assert result["system_violation_count"] == 0, result["per_scenario"]
    assert result["total_cases"] == len(ALL_SCENARIOS)
