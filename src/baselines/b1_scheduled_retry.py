"""B1 — Scheduled Retry. Coarse reason awareness (skips publicly-known hard
declines), T+24h / T+72h, max 2 attempts, one generic reminder after final
failure. A *reasonable* baseline — what a team that read the decline-code
docs but didn't build an LLM agent would ship.
"""

from __future__ import annotations

from datetime import timedelta

from domain.actions import Action, ActionType
from domain.context import Context
from domain.events import PaymentEvent
from domain.reason_knowledge import HARD_DECLINE_REASONS
from domain.strategy import Strategy

MAX_ATTEMPTS = 2
DELAYS_HOURS = [24, 72]


class ScheduledRetry(Strategy):
    name = "B1_scheduled_retry"

    def propose(self, event: PaymentEvent, ctx: Context) -> Action | None:
        if event.reason in HARD_DECLINE_REASONS:
            if ctx.last_contact_at is None:
                return Action(
                    action_type=ActionType.NUDGE,
                    payment_id=event.payment_id,
                    order_id=event.order_id,
                    customer_id=event.customer_id,
                    scheduled_at=event.occurred_at + timedelta(hours=1),
                    message="Your payment could not be completed — please update your payment method.",
                    reasoning=f"{event.reason.value} is a known hard decline; not retryable",
                    confidence=0.9,
                    diagnosed_reason=event.reason.value,
                )
            return None

        if ctx.invoice_already_settled:
            return None

        if ctx.attempts_so_far < MAX_ATTEMPTS:
            delay = DELAYS_HOURS[ctx.attempts_so_far]
            return Action(
                action_type=ActionType.RETRY,
                payment_id=event.payment_id,
                order_id=event.order_id,
                customer_id=event.customer_id,
                scheduled_at=event.occurred_at + timedelta(hours=delay),
                rail=event.rail.value,
                reasoning="scheduled retry: coarse reason awareness, fixed T+24h/T+72h",
                confidence=0.7,
                diagnosed_reason=event.reason.value,
            )

        if ctx.last_contact_at is None:
            return Action(
                action_type=ActionType.NUDGE,
                payment_id=event.payment_id,
                order_id=event.order_id,
                customer_id=event.customer_id,
                scheduled_at=event.occurred_at + timedelta(hours=DELAYS_HOURS[-1] + 1),
                message="We couldn't complete your payment after multiple attempts — please try again.",
                reasoning="final reminder after exhausting scheduled retries",
                confidence=0.6,
                diagnosed_reason=event.reason.value,
            )
        return None
