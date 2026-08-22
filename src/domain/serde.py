"""Explicit to_dict/from_dict for domain types. Pure conversion, zero I/O —
callers (generator, world, audit) do the actual file writing."""

from __future__ import annotations

from datetime import datetime

from domain.actions import Action, ActionType
from domain.context import Context
from domain.customer import Customer
from domain.events import FailureReason, PaymentEvent, Rail


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _parse(dt: str | None) -> datetime | None:
    return datetime.fromisoformat(dt) if dt is not None else None


def event_to_dict(e: PaymentEvent) -> dict:
    return {
        "event_id": e.event_id,
        "payment_id": e.payment_id,
        "order_id": e.order_id,
        "customer_id": e.customer_id,
        "amount": e.amount,
        "currency": e.currency,
        "rail": e.rail.value,
        "reason": e.reason.value,
        "occurred_at": _iso(e.occurred_at),
        "attempt_number": e.attempt_number,
        "mandate_id": e.mandate_id,
        "gateway_message": e.gateway_message,
        "metadata": e.metadata,
    }


def event_from_dict(d: dict) -> PaymentEvent:
    return PaymentEvent(
        event_id=d["event_id"],
        payment_id=d["payment_id"],
        order_id=d["order_id"],
        customer_id=d["customer_id"],
        amount=d["amount"],
        currency=d["currency"],
        rail=Rail(d["rail"]),
        reason=FailureReason(d["reason"]),
        occurred_at=_parse(d["occurred_at"]),
        attempt_number=d.get("attempt_number", 1),
        mandate_id=d.get("mandate_id"),
        gateway_message=d.get("gateway_message"),
        metadata=d.get("metadata", {}),
    )


def customer_to_dict(c: Customer) -> dict:
    return {
        "customer_id": c.customer_id,
        "name": c.name,
        "timezone": c.timezone,
        "do_not_contact": c.do_not_contact,
        "risk_flagged": c.risk_flagged,
        "last_contacted_at": _iso(c.last_contacted_at),
    }


def customer_from_dict(d: dict) -> Customer:
    return Customer(
        customer_id=d["customer_id"],
        name=d["name"],
        timezone=d.get("timezone", "Asia/Kolkata"),
        do_not_contact=d.get("do_not_contact", False),
        risk_flagged=d.get("risk_flagged", False),
        last_contacted_at=_parse(d.get("last_contacted_at")),
    )


def action_to_dict(a: Action) -> dict:
    return {
        "action_type": a.action_type.value,
        "payment_id": a.payment_id,
        "order_id": a.order_id,
        "customer_id": a.customer_id,
        "scheduled_at": _iso(a.scheduled_at),
        "rail": a.rail,
        "message": a.message,
        "reasoning": a.reasoning,
        "confidence": a.confidence,
        "diagnosed_reason": a.diagnosed_reason,
        "metadata": a.metadata,
    }


def action_from_dict(d: dict) -> Action:
    return Action(
        action_type=ActionType(d["action_type"]),
        payment_id=d["payment_id"],
        order_id=d["order_id"],
        customer_id=d["customer_id"],
        scheduled_at=_parse(d["scheduled_at"]),
        rail=d.get("rail"),
        message=d.get("message"),
        reasoning=d.get("reasoning", ""),
        confidence=d.get("confidence", 0.0),
        diagnosed_reason=d.get("diagnosed_reason"),
        metadata=d.get("metadata", {}),
    )


def context_to_dict(ctx: Context) -> dict:
    return {
        "now": _iso(ctx.now),
        "customer": customer_to_dict(ctx.customer),
        "attempts_so_far": ctx.attempts_so_far,
        "mandate_presentations_so_far": ctx.mandate_presentations_so_far,
        "last_failure_reason": ctx.last_failure_reason,
        "last_attempt_at": _iso(ctx.last_attempt_at),
        "failure_at": _iso(ctx.failure_at),
        "invoice_already_settled": ctx.invoice_already_settled,
        "refund_in_flight": ctx.refund_in_flight,
        "open_chargeback": ctx.open_chargeback,
        "last_contact_at": _iso(ctx.last_contact_at),
        "amount": ctx.amount,
        "amount_ceiling": ctx.amount_ceiling,
        "extra": ctx.extra,
    }


def context_from_dict(d: dict) -> Context:
    """Safety-relevant fields are required, not defaulted — a truncated or
    tampered record must fail loudly (KeyError) rather than silently
    reconstruct a falsely-safe Context (e.g. a missing `open_chargeback`
    defaulting to False could replay a correctly-DENIED decision as ALLOW).
    Only genuinely optional/nullable fields use .get()."""
    return Context(
        now=_parse(d["now"]),
        customer=customer_from_dict(d["customer"]),
        attempts_so_far=d["attempts_so_far"],
        mandate_presentations_so_far=d["mandate_presentations_so_far"],
        last_failure_reason=d.get("last_failure_reason"),
        last_attempt_at=_parse(d.get("last_attempt_at")),
        failure_at=_parse(d.get("failure_at")),
        invoice_already_settled=d["invoice_already_settled"],
        refund_in_flight=d["refund_in_flight"],
        open_chargeback=d["open_chargeback"],
        last_contact_at=_parse(d.get("last_contact_at")),
        amount=d["amount"],
        amount_ceiling=d.get("amount_ceiling"),
        extra=d["extra"],
    )
