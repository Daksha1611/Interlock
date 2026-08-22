"""The context snapshot the gate evaluates an Action against.

Pure data — assembled by callers from ledger/mandate/customer state, never
fetched by the gate itself. Keeping this a plain dataclass (not a live
lookup) is what makes gate decisions replayable offline: the same Context
always yields the same GateDecision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from domain.customer import Customer


@dataclass(frozen=True)
class Context:
    now: datetime
    customer: Customer

    # attempt / mandate state
    attempts_so_far: int = 0
    mandate_presentations_so_far: int = 0
    last_failure_reason: str | None = None
    last_attempt_at: datetime | None = None
    failure_at: datetime | None = None   # when the order's first failure occurred

    # ledger / money state
    invoice_already_settled: bool = False
    refund_in_flight: bool = False
    open_chargeback: bool = False

    # contact state
    last_contact_at: datetime | None = None

    # economics
    amount: int = 0
    amount_ceiling: int | None = None

    extra: dict = field(default_factory=dict)
