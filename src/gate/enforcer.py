"""The gate. Ordinary Python reading config/policy.yaml — no model call, no
prompt, no natural language anywhere in this decision path. This is the
centrepiece: the agent proposes, this disposes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from enum import Enum

from domain.actions import Action, ActionType
from domain.context import Context
from gate.rules import ALL_RULES, RuleResult


class Outcome(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    MODIFY = "MODIFY"


@dataclass(frozen=True)
class GateDecision:
    outcome: Outcome
    action: Action                  # the action as proposed
    final_action: Action | None     # None on DENY; the (possibly rescheduled) action otherwise
    reason: str
    rule_results: list[RuleResult]


class Gate:
    """Deterministic. No model call. Every outcome logged.

    Returns ALLOW, DENY(reason), or MODIFY(new_action, reason).
    """

    def __init__(self, policy: dict):
        self.policy = policy

    def evaluate(self, action: Action, ctx: Context) -> GateDecision:
        fixed, notes = self._autofix(action, ctx)
        results = [rule(fixed, ctx, self.policy) for rule in ALL_RULES]
        failed = [r for r in results if not r.passed]

        if failed:
            reason = "; ".join(f"{r.rule}: {r.detail}" for r in failed)
            return GateDecision(Outcome.DENY, action, None, reason, results)

        if notes:
            return GateDecision(Outcome.MODIFY, action, fixed, "; ".join(notes), results)

        return GateDecision(Outcome.ALLOW, action, fixed, "all invariants satisfied", results)

    def _autofix(self, action: Action, ctx: Context) -> tuple[Action, list[str]]:
        """Deterministically reschedule around contact-frequency / quiet-hours
        instead of an outright deny, when a schedule change alone would
        satisfy the invariant. Every other violation still hard-denies —
        this never changes *what* the action does, only *when* a NUDGE fires."""
        if action.action_type != ActionType.NUDGE:
            return action, []

        notes: list[str] = []
        fixed = action

        if ctx.last_contact_at is not None:
            earliest = ctx.last_contact_at + timedelta(hours=self.policy["contact_frequency_hours"])
            if fixed.scheduled_at < earliest:
                fixed = replace(fixed, scheduled_at=earliest)
                notes.append(f"rescheduled past contact-frequency window to {earliest.isoformat()}")

        start, end = self.policy["quiet_hours_start"], self.policy["quiet_hours_end"]
        hour = fixed.scheduled_at.hour
        if hour >= start:
            new_time = (fixed.scheduled_at + timedelta(days=1)).replace(hour=end, minute=0, second=0, microsecond=0)
            fixed = replace(fixed, scheduled_at=new_time)
            notes.append(f"rescheduled off quiet hours to {new_time.isoformat()}")
        elif hour < end:
            new_time = fixed.scheduled_at.replace(hour=end, minute=0, second=0, microsecond=0)
            fixed = replace(fixed, scheduled_at=new_time)
            notes.append(f"rescheduled off quiet hours to {new_time.isoformat()}")

        return fixed, notes
