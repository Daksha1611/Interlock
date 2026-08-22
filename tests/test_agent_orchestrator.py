"""Unit test for the agent's failure-handling — no network, no API key
needed. Mocks agent.diagnose.diagnose directly."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from domain.actions import ActionType
from domain.context import Context
from domain.customer import Customer
from domain.events import FailureReason, PaymentEvent, Rail


def test_agent_escalates_instead_of_crashing_on_llm_failure():
    from agent.orchestrator import AgentStrategy

    event = PaymentEvent(
        event_id="e1", payment_id="p1", order_id="o1", customer_id="c1", amount=1000,
        currency="INR", rail=Rail.CARD, reason=FailureReason.GATEWAY_TIMEOUT,
        occurred_at=datetime(2026, 7, 1),
    )
    ctx = Context(now=datetime(2026, 7, 1, 1), customer=Customer(customer_id="c1", name="Test"))

    with patch("agent.orchestrator.diagnose", side_effect=RuntimeError("OpenRouter call failed after 4 attempts")):
        action = AgentStrategy().propose(event, ctx)

    assert action is not None
    assert action.action_type == ActionType.ESCALATE
    assert action.confidence == 0.0
    assert "OpenRouter call failed" in action.reasoning
