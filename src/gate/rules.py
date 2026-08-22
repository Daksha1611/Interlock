"""One pure function per invariant (§3.1 of the spec). Every function has
the signature (action, ctx, policy) -> RuleResult, takes no I/O, and is
independently unit-testable without ever running an LLM. This is what makes
the safety claim provable rather than asserted.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.actions import Action, ActionType
from domain.context import Context
from domain.reason_knowledge import HARD_DECLINE_REASONS

RETRY_LIKE = {ActionType.RETRY, ActionType.SWITCH_RAIL}


@dataclass(frozen=True)
class RuleResult:
    rule: str
    passed: bool
    detail: str = ""


def attempt_cap(action: Action, ctx: Context, policy: dict) -> RuleResult:
    if action.action_type not in RETRY_LIKE:
        return RuleResult("attempt_cap", True)
    cap = policy["attempt_cap"]
    ok = ctx.attempts_so_far < cap
    return RuleResult("attempt_cap", ok, f"{ctx.attempts_so_far}/{cap} attempts already used")


def mandate_cap(action: Action, ctx: Context, policy: dict) -> RuleResult:
    if action.action_type not in RETRY_LIKE or not ctx.extra.get("mandate_id"):
        return RuleResult("mandate_cap", True)
    cap = policy["mandate_presentation_cap"]
    ok = ctx.mandate_presentations_so_far < cap
    return RuleResult("mandate_cap", ok, f"{ctx.mandate_presentations_so_far}/{cap} presentations already used")


def cooling_off(action: Action, ctx: Context, policy: dict) -> RuleResult:
    if action.action_type not in RETRY_LIKE or ctx.last_failure_reason != "INSUFFICIENT_FUNDS":
        return RuleResult("cooling_off", True)
    if ctx.failure_at is None:
        return RuleResult("cooling_off", True)
    elapsed_h = (action.scheduled_at - ctx.failure_at).total_seconds() / 3600
    cap = policy["cooling_off_hours"]
    ok = elapsed_h >= cap
    return RuleResult("cooling_off", ok, f"only {elapsed_h:.1f}h since INSUFFICIENT_FUNDS, needs {cap}h")


NO_OP_TYPES = {ActionType.ESCALATE, ActionType.STOP}  # never move money or contact anyone


def risk_block(action: Action, ctx: Context, policy: dict) -> RuleResult:
    if action.action_type in NO_OP_TYPES:
        return RuleResult("risk_block", True)
    risky = ctx.last_failure_reason == "RISK_BLOCK" or bool(ctx.extra.get("risk_flagged"))
    return RuleResult("risk_block", not risky, "risk-flagged account: escalate only, no retry and no contact" if risky else "")


def hard_decline_no_retry(action: Action, ctx: Context, policy: dict) -> RuleResult:
    """Reasons that are publicly known to be non-retryable (see
    domain.reason_knowledge) may never be retried, regardless of how much
    attempt-cap headroom remains — retrying an expired card or a revoked
    mandate is a wasted attempt at best and a mandate-rules breach at worst."""
    if action.action_type not in RETRY_LIKE:
        return RuleResult("hard_decline_no_retry", True)
    reason = ctx.last_failure_reason
    is_hard = reason is not None and reason in {r.value for r in HARD_DECLINE_REASONS}
    return RuleResult(
        "hard_decline_no_retry", not is_hard, f"{reason} is a known non-retryable decline" if is_hard else ""
    )


def ledger_settled(action: Action, ctx: Context, policy: dict) -> RuleResult:
    if action.action_type not in RETRY_LIKE:
        return RuleResult("ledger_settled", True)
    settled = ctx.invoice_already_settled
    return RuleResult("ledger_settled", not settled, "ledger already shows this invoice settled" if settled else "")


def refund_interlock(action: Action, ctx: Context, policy: dict) -> RuleResult:
    if action.action_type not in RETRY_LIKE:
        return RuleResult("refund_interlock", True)
    blocked = ctx.refund_in_flight
    return RuleResult("refund_interlock", not blocked, "refund in flight on this order" if blocked else "")


def dispute_interlock(action: Action, ctx: Context, policy: dict) -> RuleResult:
    if action.action_type in NO_OP_TYPES:
        return RuleResult("dispute_interlock", True)
    blocked = ctx.open_chargeback
    return RuleResult(
        "dispute_interlock", not blocked, "open chargeback on this order: no action except escalate" if blocked else ""
    )


def do_not_contact(action: Action, ctx: Context, policy: dict) -> RuleResult:
    if action.action_type != ActionType.NUDGE:
        return RuleResult("do_not_contact", True)
    dnc = bool(ctx.customer.do_not_contact) or bool(ctx.extra.get("do_not_contact"))
    return RuleResult("do_not_contact", not dnc, "customer is on the do-not-contact list" if dnc else "")


def contact_frequency(action: Action, ctx: Context, policy: dict) -> RuleResult:
    if action.action_type != ActionType.NUDGE or ctx.last_contact_at is None:
        return RuleResult("contact_frequency", True)
    elapsed_h = (action.scheduled_at - ctx.last_contact_at).total_seconds() / 3600
    cap = policy["contact_frequency_hours"]
    ok = elapsed_h >= cap
    return RuleResult("contact_frequency", ok, f"only {elapsed_h:.1f}h since last contact, needs {cap}h")


def quiet_hours(action: Action, ctx: Context, policy: dict) -> RuleResult:
    if action.action_type != ActionType.NUDGE:
        return RuleResult("quiet_hours", True)
    hour = action.scheduled_at.hour
    start, end = policy["quiet_hours_start"], policy["quiet_hours_end"]
    in_quiet = hour >= start or hour < end
    return RuleResult(
        "quiet_hours", not in_quiet, f"scheduled {hour:02d}:00 IST falls in quiet hours {start:02d}:00-{end:02d}:00" if in_quiet else ""
    )


def amount_ceiling(action: Action, ctx: Context, policy: dict) -> RuleResult:
    if action.action_type not in RETRY_LIKE:
        return RuleResult("amount_ceiling", True)
    ceiling = ctx.amount_ceiling if ctx.amount_ceiling is not None else policy.get("amount_ceiling")
    if ceiling is None:
        return RuleResult("amount_ceiling", True)
    ok = ctx.amount <= ceiling
    return RuleResult(
        "amount_ceiling", ok, f"amount {ctx.amount} exceeds ceiling {ceiling}: escalate instead of auto-retry" if not ok else ""
    )


ALL_RULES = [
    attempt_cap,
    mandate_cap,
    cooling_off,
    risk_block,
    hard_decline_no_retry,
    ledger_settled,
    refund_interlock,
    dispute_interlock,
    do_not_contact,
    contact_frequency,
    quiet_hours,
    amount_ceiling,
]
