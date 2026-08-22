"""Pure event types. Zero I/O, zero imports from other src/ packages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class FailureReason(str, Enum):
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    ISSUER_DOWN = "ISSUER_DOWN"
    GATEWAY_TIMEOUT = "GATEWAY_TIMEOUT"
    EXPIRED_CARD = "EXPIRED_CARD"
    DO_NOT_HONOR = "DO_NOT_HONOR"
    THREE_DS_ABANDONED = "THREE_DS_ABANDONED"
    MANDATE_REVOKED = "MANDATE_REVOKED"
    MANDATE_INSUFFICIENT_BALANCE = "MANDATE_INSUFFICIENT_BALANCE"
    INVALID_VPA = "INVALID_VPA"
    UPI_TIMEOUT = "UPI_TIMEOUT"
    RISK_BLOCK = "RISK_BLOCK"


class Rail(str, Enum):
    CARD = "CARD"
    UPI = "UPI"
    NETBANKING = "NETBANKING"
    EMANDATE = "EMANDATE"
    WALLET = "WALLET"


@dataclass(frozen=True)
class PaymentEvent:
    """A single failed-payment event as observed by the agent.

    Only fields an agent could plausibly observe belong here — no ground-truth
    recovery probabilities. Those live exclusively in world/outcome_model.py.
    """

    event_id: str
    payment_id: str
    order_id: str
    customer_id: str
    amount: int  # smallest currency unit (paise)
    currency: str
    rail: Rail
    reason: FailureReason
    occurred_at: datetime
    attempt_number: int = 1
    mandate_id: str | None = None
    gateway_message: str | None = None
    metadata: dict = field(default_factory=dict)
