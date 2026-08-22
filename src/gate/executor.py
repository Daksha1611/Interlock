"""The ONLY caller of money-moving and customer-contact actions. Nothing in
agent/ imports this module — enforced by tests/test_isolation.py. A prompt
injection that changes what the agent *proposes* still changes nothing
about what *happens*, because the agent has no path to this function.

Only called by src/eval/harness.py, and only for a GateDecision whose
outcome is ALLOW or MODIFY. A DENY never reaches here.
"""

from __future__ import annotations

import numpy as np

from domain.actions import Action, ActionType
from world.ledger import Ledger, SettlementEvent
from world.outcome_model import resolve_nudge, resolve_retry


def execute(action: Action, ledger: Ledger, taxonomy: dict, rng: np.random.Generator) -> dict:
    order_id = action.order_id
    state = ledger.orders[order_id]
    true_reason = state.truth.reason  # resolution always uses ground truth, never the proposer's guess

    if action.action_type in (ActionType.RETRY, ActionType.SWITCH_RAIL):
        hours = (action.scheduled_at - state.truth.first_failure_at).total_seconds() / 3600
        contacted = len(state.contacts) > 0
        success = resolve_retry(rng, taxonomy, true_reason, hours, contacted=contacted)
        ledger.record_attempt(order_id, action.scheduled_at, success)
        if state.truth.mandate_id:
            ledger.record_mandate_presentation(order_id)
        return {
            "executed": True,
            "action_type": action.action_type.value,
            "success": success,
            "money_delta": state.truth.amount if success else 0,
        }

    if action.action_type == ActionType.NUDGE:
        ledger.record_contact(order_id, action.scheduled_at)
        success = resolve_nudge(rng, taxonomy, true_reason)
        if success:
            state.settlements.append(
                SettlementEvent(at=action.scheduled_at, via="nudge", amount=state.truth.amount)
            )
        return {
            "executed": True,
            "action_type": action.action_type.value,
            "success": success,
            "money_delta": state.truth.amount if success else 0,
        }

    if action.action_type == ActionType.ESCALATE:
        return {"executed": True, "action_type": "ESCALATE", "success": None, "money_delta": 0}

    return {"executed": False, "action_type": action.action_type.value, "success": None, "money_delta": 0}
