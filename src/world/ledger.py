"""The money source of truth for one simulation run. Tracks every
settlement per order and is the sole authority on whether a double-charge
happened. Mutable simulation state — separate from the frozen ground-truth
facts fixed at corpus-generation time (OrderGroundTruth).

world/ shares no imports with agent/ — see tests/test_isolation.py. The
harness (src/eval/harness.py) is the only caller that wires ledger state
into a domain.Context for a strategy or the gate to read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from domain.context import Context
from domain.customer import Customer

REFUND_DEFAULT_WINDOW_HOURS = 72


@dataclass(frozen=True)
class OrderGroundTruth:
    """Facts fixed once at generation time. No strategy ever reads this
    object directly — only through the Context the harness derives from it
    via Ledger.get_context()."""

    order_id: str
    payment_id: str
    customer_id: str
    amount: int
    rail: str
    reason: str
    first_failure_at: datetime
    mandate_id: str | None = None
    already_succeeded: bool = False        # settled immediately, despite the reported failure
    external_settlement_at: datetime | None = None   # settled later via another channel
    refund_in_flight_at: datetime | None = None
    refund_window_hours: float = REFUND_DEFAULT_WINDOW_HOURS
    open_chargeback_at: datetime | None = None
    risk_flagged_at: datetime | None = None
    dnc_added_at: datetime | None = None
    duplicate_webhook: bool = False


@dataclass
class SettlementEvent:
    at: datetime
    via: str  # "already_succeeded" | "external" | "retry"
    amount: int


@dataclass
class OrderState:
    truth: OrderGroundTruth
    settlements: list[SettlementEvent] = field(default_factory=list)
    attempt_timestamps: list[datetime] = field(default_factory=list)
    mandate_presentations: int = 0
    contacts: list[datetime] = field(default_factory=list)

    def is_settled(self, now: datetime) -> bool:
        return any(s.at <= now for s in self.settlements)

    def double_charged(self) -> bool:
        return len(self.settlements) > 1

    def refund_in_flight(self, now: datetime) -> bool:
        t = self.truth.refund_in_flight_at
        if t is None or now < t:
            return False
        window = timedelta(hours=self.truth.refund_window_hours)
        return now <= t + window

    def open_chargeback(self, now: datetime) -> bool:
        t = self.truth.open_chargeback_at
        return t is not None and now >= t

    def risk_flagged(self, now: datetime) -> bool:
        t = self.truth.risk_flagged_at
        return t is not None and now >= t

    def dnc(self, now: datetime) -> bool:
        t = self.truth.dnc_added_at
        return t is not None and now >= t


class Ledger:
    """Owns the mutable state for one simulation run over one corpus."""

    def __init__(self, ground_truths: list[OrderGroundTruth], customers: list[Customer]):
        self.orders: dict[str, OrderState] = {}
        self.customers: dict[str, Customer] = {c.customer_id: c for c in customers}
        for gt in ground_truths:
            state = OrderState(truth=gt)
            if gt.already_succeeded:
                state.settlements.append(
                    SettlementEvent(at=gt.first_failure_at, via="already_succeeded", amount=gt.amount)
                )
            if gt.external_settlement_at is not None:
                state.settlements.append(
                    SettlementEvent(at=gt.external_settlement_at, via="external", amount=gt.amount)
                )
            self.orders[gt.order_id] = state

    def get_context(self, order_id: str, now: datetime, amount_ceiling: int | None = None) -> Context:
        state = self.orders[order_id]
        customer = self.customers[state.truth.customer_id]
        return Context(
            now=now,
            customer=customer,
            attempts_so_far=len([t for t in state.attempt_timestamps if t <= now]),
            mandate_presentations_so_far=state.mandate_presentations,
            last_failure_reason=state.truth.reason,
            last_attempt_at=max((t for t in state.attempt_timestamps if t <= now), default=None),
            failure_at=state.truth.first_failure_at,
            invoice_already_settled=state.is_settled(now),
            refund_in_flight=state.refund_in_flight(now),
            open_chargeback=state.open_chargeback(now),
            last_contact_at=max((t for t in state.contacts if t <= now), default=None),
            amount=state.truth.amount,
            amount_ceiling=amount_ceiling,
            extra={
                "risk_flagged": customer.risk_flagged or state.risk_flagged(now),
                "do_not_contact": customer.do_not_contact or state.dnc(now),
                "mandate_id": state.truth.mandate_id,
                "rail": state.truth.rail,
            },
        )

    def record_attempt(self, order_id: str, at: datetime, success: bool) -> None:
        state = self.orders[order_id]
        state.attempt_timestamps.append(at)
        if success:
            state.settlements.append(SettlementEvent(at=at, via="retry", amount=state.truth.amount))

    def record_contact(self, order_id: str, at: datetime) -> None:
        self.orders[order_id].contacts.append(at)

    def record_mandate_presentation(self, order_id: str) -> None:
        self.orders[order_id].mandate_presentations += 1

    # --- read-side helpers for eval/metrics.py ---

    def double_charged_order_ids(self) -> list[str]:
        return [oid for oid, s in self.orders.items() if s.double_charged()]

    def total_recovered(self) -> int:
        total = 0
        for state in self.orders.values():
            retry_settlements = [s for s in state.settlements if s.via == "retry"]
            total += sum(s.amount for s in retry_settlements)
        return total

    def total_attempts(self) -> int:
        return sum(len(s.attempt_timestamps) for s in self.orders.values())

    def total_contacts(self) -> int:
        return sum(len(s.contacts) for s in self.orders.values())


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _parse(dt: str | None) -> datetime | None:
    return datetime.fromisoformat(dt) if dt is not None else None


def ground_truth_to_dict(gt: OrderGroundTruth) -> dict:
    return {
        "order_id": gt.order_id,
        "payment_id": gt.payment_id,
        "customer_id": gt.customer_id,
        "amount": gt.amount,
        "rail": gt.rail,
        "reason": gt.reason,
        "first_failure_at": _iso(gt.first_failure_at),
        "mandate_id": gt.mandate_id,
        "already_succeeded": gt.already_succeeded,
        "external_settlement_at": _iso(gt.external_settlement_at),
        "refund_in_flight_at": _iso(gt.refund_in_flight_at),
        "refund_window_hours": gt.refund_window_hours,
        "open_chargeback_at": _iso(gt.open_chargeback_at),
        "risk_flagged_at": _iso(gt.risk_flagged_at),
        "dnc_added_at": _iso(gt.dnc_added_at),
        "duplicate_webhook": gt.duplicate_webhook,
    }


def ground_truth_from_dict(d: dict) -> OrderGroundTruth:
    return OrderGroundTruth(
        order_id=d["order_id"],
        payment_id=d["payment_id"],
        customer_id=d["customer_id"],
        amount=d["amount"],
        rail=d["rail"],
        reason=d["reason"],
        first_failure_at=_parse(d["first_failure_at"]),
        mandate_id=d.get("mandate_id"),
        already_succeeded=d.get("already_succeeded", False),
        external_settlement_at=_parse(d.get("external_settlement_at")),
        refund_in_flight_at=_parse(d.get("refund_in_flight_at")),
        refund_window_hours=d.get("refund_window_hours", REFUND_DEFAULT_WINDOW_HOURS),
        open_chargeback_at=_parse(d.get("open_chargeback_at")),
        risk_flagged_at=_parse(d.get("risk_flagged_at")),
        dnc_added_at=_parse(d.get("dnc_added_at")),
        duplicate_webhook=d.get("duplicate_webhook", False),
    )
