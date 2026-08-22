"""B0 — Blind Retry. Every failure, same rail, T+1h / T+2h / T+3h, max 3,
no contact, no reason awareness. What a naive cron job does — and what many
real integrations actually run today. Deliberately ignores everything: the
ledger, the customer, the reason. The gate is what keeps this from being
dangerous.
"""

from __future__ import annotations

from datetime import timedelta

from domain.actions import Action, ActionType
from domain.context import Context
from domain.events import PaymentEvent
from domain.strategy import Strategy

MAX_ATTEMPTS = 3
DELAYS_HOURS = [1, 2, 3]


class BlindRetry(Strategy):
    name = "B0_blind_retry"

    def propose(self, event: PaymentEvent, ctx: Context) -> Action | None:
        if ctx.attempts_so_far >= MAX_ATTEMPTS:
            return None
        delay = DELAYS_HOURS[ctx.attempts_so_far]
        return Action(
            action_type=ActionType.RETRY,
            payment_id=event.payment_id,
            order_id=event.order_id,
            customer_id=event.customer_id,
            scheduled_at=event.occurred_at + timedelta(hours=delay),
            rail=event.rail.value,
            reasoning="blind retry: fixed schedule, no reason awareness",
            confidence=1.0,
            diagnosed_reason=None,
        )
