"""Sampling helpers for corpus generation. Reads only `frequency` and rail
correlation — never the recovery curves in taxonomy.yaml (those are the
simulator's ground truth, off-limits here)."""

from __future__ import annotations

import numpy as np

from domain.events import FailureReason, Rail

# Which rails a given failure reason can plausibly occur on. Purely
# descriptive of how the failure was observed — not a probability leak.
REASON_RAILS: dict[FailureReason, list[Rail]] = {
    FailureReason.INSUFFICIENT_FUNDS: [Rail.CARD, Rail.UPI, Rail.NETBANKING, Rail.WALLET],
    FailureReason.ISSUER_DOWN: [Rail.CARD, Rail.NETBANKING],
    FailureReason.GATEWAY_TIMEOUT: [Rail.CARD, Rail.UPI, Rail.NETBANKING, Rail.WALLET],
    FailureReason.EXPIRED_CARD: [Rail.CARD],
    FailureReason.DO_NOT_HONOR: [Rail.CARD],
    FailureReason.THREE_DS_ABANDONED: [Rail.CARD],
    FailureReason.MANDATE_REVOKED: [Rail.EMANDATE],
    FailureReason.MANDATE_INSUFFICIENT_BALANCE: [Rail.EMANDATE],
    FailureReason.INVALID_VPA: [Rail.UPI],
    FailureReason.UPI_TIMEOUT: [Rail.UPI],
    FailureReason.RISK_BLOCK: [Rail.CARD, Rail.UPI, Rail.NETBANKING, Rail.WALLET, Rail.EMANDATE],
}

MANDATE_REASONS = {FailureReason.MANDATE_REVOKED, FailureReason.MANDATE_INSUFFICIENT_BALANCE}


def sample_reason(rng: np.random.Generator, taxonomy: dict) -> FailureReason:
    reasons = list(taxonomy["reasons"].keys())
    weights = np.array([taxonomy["reasons"][r]["frequency"] for r in reasons], dtype=float)
    weights = weights / weights.sum()
    choice = rng.choice(reasons, p=weights)
    return FailureReason(choice)


def sample_rail(rng: np.random.Generator, reason: FailureReason) -> Rail:
    options = REASON_RAILS[reason]
    return options[rng.integers(0, len(options))]


def sample_amount(rng: np.random.Generator, cfg: dict) -> int:
    raw = rng.lognormal(mean=np.log(cfg["mean_paise"]), sigma=cfg["sigma"])
    return int(min(max(raw, cfg["min_paise"]), cfg["max_paise"]))


def bernoulli(rng: np.random.Generator, p: float) -> bool:
    return bool(rng.random() < p)
