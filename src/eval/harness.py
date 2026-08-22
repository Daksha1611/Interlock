"""Runs one strategy (B0, B1, or the agent) over a corpus through the SAME
gate and executor every strategy goes through — the comparison is only fair,
and the safety claim only means something, if nothing gets a side channel
to the money. See config/simulation.yaml for corpus generation and
world/outcome_model.py for the (hidden) ground truth this resolves against.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import numpy as np

from audit.trail import AuditTrail, DecisionRecord
from domain.actions import ActionType
from domain.customer import Customer
from domain.events import PaymentEvent
from domain.serde import action_to_dict, context_to_dict, event_to_dict
from domain.strategy import Strategy
from gate.enforcer import Gate, Outcome
from gate.executor import execute
from world.ledger import Ledger, OrderGroundTruth

TERMINAL_TYPES = {ActionType.ESCALATE}
DEFAULT_HORIZON_HOURS = 168
DEFAULT_MAX_STEPS = 20


def group_by_order(events: list[PaymentEvent]) -> dict[str, list[PaymentEvent]]:
    by_order: dict[str, list[PaymentEvent]] = {}
    for e in events:
        by_order.setdefault(e.order_id, []).append(e)
    for evts in by_order.values():
        evts.sort(key=lambda e: e.occurred_at)
    return by_order


def run_strategy(
    strategy: Strategy,
    events: list[PaymentEvent],
    ground_truths: list[OrderGroundTruth],
    customers: list[Customer],
    policy: dict,
    taxonomy: dict,
    seed: int,
    horizon_hours: int = DEFAULT_HORIZON_HOURS,
    max_steps_per_order: int = DEFAULT_MAX_STEPS,
    run_id: str | None = None,
    audit: AuditTrail | None = None,
) -> dict:
    run_id = run_id or f"run_{strategy.name}_{uuid.uuid4().hex[:10]}"
    if audit is None:
        audit = AuditTrail(run_id)

    rng = np.random.default_rng(seed)
    ledger = Ledger(ground_truths, customers)
    gate = Gate(policy)

    by_order = group_by_order(events)
    n_decisions = 0
    unresolved_order_ids: list[str] = []

    for order_id, evts in by_order.items():
        first_event = evts[0]
        now = first_event.occurred_at
        resolved = False

        for step in range(max_steps_per_order):
            ctx = ledger.get_context(order_id, now, amount_ceiling=policy.get("amount_ceiling"))
            proposed = strategy.propose(first_event, ctx)

            if proposed is None or proposed.action_type == ActionType.STOP:
                break
            if (proposed.scheduled_at - first_event.occurred_at) > timedelta(hours=horizon_hours):
                break

            decision = gate.evaluate(proposed, ctx)
            outcome = None
            if decision.outcome in (Outcome.ALLOW, Outcome.MODIFY):
                final = decision.final_action
                outcome = execute(final, ledger, taxonomy, rng)
                now = final.scheduled_at

            record = DecisionRecord(
                decision_id=f"dec_{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                strategy_name=strategy.name,
                step=step,
                order_id=order_id,
                payment_id=first_event.payment_id,
                event=event_to_dict(first_event),
                context_snapshot=context_to_dict(ctx),
                diagnosis={
                    "reason": proposed.diagnosed_reason,
                    "confidence": proposed.confidence,
                    "reasoning": proposed.reasoning,
                },
                proposed_action=action_to_dict(proposed),
                rule_results=[
                    {"rule": r.rule, "passed": r.passed, "detail": r.detail} for r in decision.rule_results
                ],
                disposition=decision.outcome.value,
                disposition_reason=decision.reason,
                final_action=action_to_dict(decision.final_action) if decision.final_action else None,
                execution_outcome=outcome,
                money_delta=outcome["money_delta"] if outcome else 0,
            )
            audit.append(record)
            n_decisions += 1

            if decision.outcome == Outcome.DENY:
                break
            if proposed.action_type in (ActionType.RETRY, ActionType.SWITCH_RAIL) and outcome and outcome["success"]:
                resolved = True
                break
            if proposed.action_type in TERMINAL_TYPES:
                break
        else:
            pass  # exhausted max_steps_per_order without resolution

        if not resolved and not ledger.orders[order_id].is_settled(now):
            unresolved_order_ids.append(order_id)

    return {
        "run_id": run_id,
        "strategy_name": strategy.name,
        "ledger": ledger,
        "n_decisions": n_decisions,
        "n_orders": len(by_order),
        "unresolved_order_ids": unresolved_order_ids,
        "audit": audit,
    }
