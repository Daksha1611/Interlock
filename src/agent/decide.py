"""Turns a Diagnosis into a proposed domain.Action. Pure translation, no
I/O — the LLM call already happened in diagnose.py. This Action is only a
proposal: it has no effect until gate/enforcer.py and gate/executor.py (which
this module never imports) act on it.
"""

from __future__ import annotations

from datetime import timedelta

from agent.diagnose import Diagnosis
from domain.actions import Action, ActionType
from domain.context import Context
from domain.events import PaymentEvent

_ACTION_MAP = {
    "RETRY": ActionType.RETRY,
    "SWITCH_RAIL": ActionType.SWITCH_RAIL,
    "NUDGE": ActionType.NUDGE,
    "STOP": ActionType.STOP,
    "ESCALATE": ActionType.ESCALATE,
}


def decide(event: PaymentEvent, ctx: Context, diagnosis: Diagnosis) -> Action:
    action_type = _ACTION_MAP[diagnosis.recommended_action]
    scheduled_at = ctx.now + timedelta(hours=diagnosis.recommended_delay_hours)

    rail = diagnosis.recommended_rail if action_type == ActionType.SWITCH_RAIL else (
        event.rail.value if action_type == ActionType.RETRY else None
    )

    return Action(
        action_type=action_type,
        payment_id=event.payment_id,
        order_id=event.order_id,
        customer_id=event.customer_id,
        scheduled_at=scheduled_at,
        rail=rail,
        message=diagnosis.recommended_message if action_type == ActionType.NUDGE else None,
        reasoning=diagnosis.reasoning,
        confidence=diagnosis.confidence,
        diagnosed_reason=diagnosis.reason,
    )
