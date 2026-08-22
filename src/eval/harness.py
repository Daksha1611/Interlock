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
        origin_event = evts[0]
        step_counter = [0]
        outcome_state = {"resolved": False, "stop": False, "now": origin_event.occurred_at}

        def take_step(trigger_event: PaymentEvent, now) -> None:
            """One propose -> gate -> (maybe) execute cycle, logged
            regardless of outcome. Mutates outcome_state / step_counter in
            the enclosing scope."""
            if step_counter[0] >= max_steps_per_order:
                outcome_state["stop"] = True
                return
            if (now - origin_event.occurred_at) > timedelta(hours=horizon_hours):
                outcome_state["stop"] = True
                return

            ctx = ledger.get_context(order_id, now, amount_ceiling=policy.get("amount_ceiling"))
            proposed = strategy.propose(trigger_event, ctx)

            if proposed is None or proposed.action_type == ActionType.STOP:
                outcome_state["stop"] = True
                return

            decision = gate.evaluate(proposed, ctx)
            exec_outcome = None
            if decision.outcome in (Outcome.ALLOW, Outcome.MODIFY):
                final = decision.final_action
                exec_outcome = execute(final, ledger, taxonomy, rng)
                outcome_state["now"] = final.scheduled_at

            record = DecisionRecord(
                decision_id=f"dec_{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                strategy_name=strategy.name,
                step=step_counter[0],
                order_id=order_id,
                payment_id=trigger_event.payment_id,
                event=event_to_dict(trigger_event),
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
                execution_outcome=exec_outcome,
                money_delta=exec_outcome["money_delta"] if exec_outcome else 0,
            )
            audit.append(record)
            nonlocal n_decisions
            n_decisions += 1
            step_counter[0] += 1

            if decision.outcome == Outcome.DENY:
                outcome_state["stop"] = True
                return
            if proposed.action_type in (ActionType.RETRY, ActionType.SWITCH_RAIL) and exec_outcome and exec_outcome["success"]:
                outcome_state["resolved"] = True
                outcome_state["stop"] = True
                return
            if proposed.action_type in TERMINAL_TYPES:
                outcome_state["stop"] = True
                return

        # Phase 1: every raw event actually delivered for this order (e.g. a
        # duplicate webhook arriving under a second event ID) is its own
        # forced decision trigger, evaluated at its own occurred_at — this
        # is what lets the gate's attempt-cap/mandate-cap invariants see and
        # block a second delivery trying to restart a sequence that already
        # exhausted its budget under the first delivery.
        for evt in evts:
            # never evaluate at a `now` earlier than the sequence has already
            # reached — a duplicate delivered 2 minutes after the original
            # must not rewind time past an action the first delivery already
            # triggered further out
            trigger_now = max(evt.occurred_at, outcome_state["now"])
            take_step(evt, trigger_now)
            if outcome_state["stop"]:
                break

        # Phase 2: once every raw delivery has been accounted for, the
        # strategy schedules its own follow-ups from the last known state.
        if not outcome_state["stop"]:
            last_event = evts[-1]
            while step_counter[0] < max_steps_per_order:
                take_step(last_event, outcome_state["now"])
                if outcome_state["stop"]:
                    break

        now = outcome_state["now"]
        if not outcome_state["resolved"] and not ledger.orders[order_id].is_settled(now):
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
