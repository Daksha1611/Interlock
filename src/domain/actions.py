"""Pure action types. Zero I/O, zero imports from other src/ packages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ActionType(str, Enum):
    RETRY = "RETRY"
    SWITCH_RAIL = "SWITCH_RAIL"
    NUDGE = "NUDGE"
    STOP = "STOP"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class Action:
    """A proposed intervention. Proposing this does nothing by itself —
    only gate/executor.py can turn it into a money-moving or customer-facing
    side effect, and only after gate/enforcer.py allows it.
    """

    action_type: ActionType
    payment_id: str
    order_id: str
    customer_id: str
    scheduled_at: datetime
    rail: str | None = None
    message: str | None = None
    reasoning: str = ""
    confidence: float = 0.0
    diagnosed_reason: str | None = None

    # Which context fields the proposer says drove this action. Read by
    # gate.rules.untrusted_provenance to decide whether the justification
    # rests on data a customer could have authored. Empty for the
    # deterministic baselines, which cite nothing because they reason over
    # nothing — and correctly never trip the rule as a result.
    cited_fields: tuple[str, ...] = ()

    metadata: dict = field(default_factory=dict)
