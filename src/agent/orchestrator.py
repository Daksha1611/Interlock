"""The agent's Strategy implementation — same interface B0/B1 implement, so
eval/harness.py runs it identically to the baselines. This is the ONLY
strategy backed by an LLM call; everything downstream (gate, executor) is
identical code regardless of which strategy proposed the action.
"""

from __future__ import annotations

from agent.decide import decide
from agent.diagnose import diagnose
from domain.actions import Action, ActionType
from domain.context import Context
from domain.events import PaymentEvent
from domain.strategy import Strategy


class AgentStrategy(Strategy):
    name = "agent_llm"

    def propose(self, event: PaymentEvent, ctx: Context) -> Action | None:
        try:
            diagnosis = diagnose(event, ctx)
        except Exception as e:
            # A transient OpenRouter failure (rate limit exhausted, outage,
            # persistently unparseable output) must not crash the whole run
            # or leave a partially-written audit trail with no explanation.
            # Consistent with the project's own thesis: when the agent can't
            # produce a confident answer, it doesn't guess — it escalates.
            return Action(
                action_type=ActionType.ESCALATE,
                payment_id=event.payment_id,
                order_id=event.order_id,
                customer_id=event.customer_id,
                scheduled_at=ctx.now,
                reasoning=f"LLM call failed, escalating rather than guessing: {e}",
                confidence=0.0,
                diagnosed_reason=None,
            )
        return decide(event, ctx, diagnosis)
