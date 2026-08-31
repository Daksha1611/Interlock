"""Unit tests for agent/diagnose.py's output validation — no network. Mocks
agent.diagnose.chat_json directly so these run without an API key."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from domain.context import Context
from domain.customer import Customer
from domain.events import FailureReason, PaymentEvent, Rail

EVENT = PaymentEvent(
    event_id="e1", payment_id="p1", order_id="o1", customer_id="c1", amount=1000,
    currency="INR", rail=Rail.CARD, reason=FailureReason.GATEWAY_TIMEOUT, occurred_at=datetime(2026, 7, 1),
)
CTX = Context(now=datetime(2026, 7, 1, 1), customer=Customer(customer_id="c1", name="Test"))


def _diagnose_with(raw: dict):
    from agent.diagnose import diagnose

    usage = {"provider": "OPENROUTER", "model": "openrouter/free", "prompt_tokens": 10, "completion_tokens": 5}
    with patch("agent.diagnose.chat_json", return_value=(raw, usage)):
        return diagnose(EVENT, CTX)


def test_invalid_reason_falls_back_to_reported_code():
    d = _diagnose_with({"diagnosed_reason": "NOT_A_REAL_REASON", "recommended_action": "STOP"})
    assert d.reason == "GATEWAY_TIMEOUT"


def test_invalid_action_falls_back_to_escalate():
    d = _diagnose_with({"diagnosed_reason": "GATEWAY_TIMEOUT", "recommended_action": "WIRE_ALL_THE_MONEY"})
    assert d.recommended_action == "ESCALATE"


def test_switch_rail_with_hallucinated_rail_falls_back_to_escalate():
    d = _diagnose_with({
        "diagnosed_reason": "GATEWAY_TIMEOUT", "recommended_action": "SWITCH_RAIL",
        "recommended_rail": "BITCOIN",
    })
    assert d.recommended_action == "ESCALATE"
    assert d.recommended_rail is None


def test_switch_rail_with_valid_rail_passes_through():
    d = _diagnose_with({
        "diagnosed_reason": "GATEWAY_TIMEOUT", "recommended_action": "SWITCH_RAIL",
        "recommended_rail": "upi",
    })
    assert d.recommended_action == "SWITCH_RAIL"
    assert d.recommended_rail == "UPI"


def test_nudge_with_no_message_gets_safe_fallback():
    d = _diagnose_with({"diagnosed_reason": "EXPIRED_CARD", "recommended_action": "NUDGE"})
    assert d.recommended_action == "NUDGE"
    assert d.recommended_message and d.recommended_message.strip()


def test_nudge_with_blank_message_gets_safe_fallback():
    d = _diagnose_with({
        "diagnosed_reason": "EXPIRED_CARD", "recommended_action": "NUDGE", "recommended_message": "   ",
    })
    assert d.recommended_message.strip()


def test_confidence_clamped_to_unit_interval():
    d = _diagnose_with({"diagnosed_reason": "GATEWAY_TIMEOUT", "recommended_action": "STOP", "confidence": 5.0})
    assert d.confidence == 1.0


def test_malformed_confidence_defaults_to_zero():
    d = _diagnose_with({"diagnosed_reason": "GATEWAY_TIMEOUT", "recommended_action": "STOP", "confidence": "high"})
    assert d.confidence == 0.0


def test_llm_usage_is_carried_through_from_chat_json():
    d = _diagnose_with({"diagnosed_reason": "GATEWAY_TIMEOUT", "recommended_action": "STOP"})
    assert d.llm_usage == {
        "provider": "OPENROUTER", "model": "openrouter/free", "prompt_tokens": 10, "completion_tokens": 5,
    }
