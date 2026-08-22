"""Public, static knowledge about decline-reason semantics — the kind of
thing documented in any card-network or UPI decline-code reference. This is
NOT the simulator's secret recovery-probability curves (those live only in
config/taxonomy.yaml, read only by world/outcome_model.py). Baselines, the
agent, and the gate may all import this freely.
"""

from __future__ import annotations

from domain.events import FailureReason

# Publicly documented as non-retryable ("hard declines") — retrying wastes
# an attempt and, for RISK_BLOCK, is itself a policy violation.
HARD_DECLINE_REASONS = frozenset(
    {
        FailureReason.EXPIRED_CARD,
        FailureReason.THREE_DS_ABANDONED,
        FailureReason.MANDATE_REVOKED,
        FailureReason.INVALID_VPA,
        FailureReason.RISK_BLOCK,
    }
)

NEVER_RETRY_REASONS = frozenset({FailureReason.RISK_BLOCK})
