"""Task 5: information-flow control over the agent's stated justification.

The claim these lock in is narrow and deliberately so: not "the model
resists injection" (undecidable, and not something a deterministic gate can
promise) but "an action whose stated basis is untrusted data cannot
execute as a money or contact action". No LLM call, no network.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from domain.actions import Action, ActionType
from domain.context import Context
from domain.customer import Customer
from domain.provenance import (
    TRUSTED_FIELDS,
    UNTRUSTED_FIELDS,
    is_untrusted,
    untrusted_citations,
)
from domain.serde import action_from_dict, action_to_dict
from gate.enforcer import Gate, Outcome
from gate.rules import untrusted_provenance

NOW = datetime(2026, 8, 1, 12, 0, 0)
POLICY = {
    "attempt_cap": 3, "mandate_presentation_cap": 2, "cooling_off_hours": 24,
    "contact_frequency_hours": 48, "quiet_hours_start": 21, "quiet_hours_end": 9,
    "amount_ceiling": 500000, "no_retry_reasons": ["RISK_BLOCK"],
}


def ctx(**kw) -> Context:
    defaults = dict(now=NOW, customer=Customer(customer_id="c1", name="Test"),
                    amount=120000, amount_ceiling=500000, last_failure_reason="GATEWAY_TIMEOUT")
    defaults.update(kw)
    return Context(**defaults)


def action(action_type=ActionType.RETRY, cited=(), **kw) -> Action:
    defaults = dict(
        action_type=action_type, payment_id="p1", order_id="o1", customer_id="c1",
        scheduled_at=NOW, rail="CARD", cited_fields=tuple(cited),
    )
    defaults.update(kw)
    if defaults["action_type"] == ActionType.NUDGE:
        defaults["message"] = defaults.get("message") or "following up"
    return Action(**defaults)


# --- the taxonomy itself ---

def test_trusted_and_untrusted_sets_are_disjoint():
    assert not (TRUSTED_FIELDS & UNTRUSTED_FIELDS)


def test_customer_authored_text_is_untrusted():
    assert is_untrusted("customer_note")
    assert is_untrusted("customer.name")


def test_ledger_and_issuer_facts_are_trusted():
    for f in ("invoice_already_settled", "attempts_so_far", "amount", "customer.risk_flagged"):
        assert not is_untrusted(f), f


def test_unknown_field_names_fail_closed_to_untrusted():
    """A hallucinated or newly-added field is the case we know least about,
    so it must not be the one that defaults to trusted."""
    assert is_untrusted("bank_confirmation_ref")
    assert untrusted_citations(["amount", "totally_made_up"]) == ("totally_made_up",)


# --- the rule ---

@pytest.mark.parametrize("action_type", [ActionType.RETRY, ActionType.SWITCH_RAIL, ActionType.NUDGE])
def test_money_or_contact_citing_untrusted_data_fails_the_rule(action_type):
    result = untrusted_provenance(action(action_type, cited=("reason", "customer_note")), ctx(), POLICY)
    assert result.passed is False
    assert "customer_note" in result.detail


@pytest.mark.parametrize("action_type", [ActionType.ESCALATE, ActionType.STOP])
def test_escalate_and_stop_are_exempt(action_type):
    """Handing a suspicious case to a human is the behaviour we want when
    untrusted text is in play — blocking it would be backwards."""
    assert untrusted_provenance(action(action_type, cited=("customer_note",)), ctx(), POLICY).passed


def test_action_citing_only_trusted_fields_passes():
    assert untrusted_provenance(action(cited=("reason", "attempts_so_far", "amount")), ctx(), POLICY).passed


def test_action_citing_nothing_passes():
    """The deterministic baselines cite nothing because they reason over
    nothing, and must not be penalised by a rule about justification."""
    assert untrusted_provenance(action(cited=()), ctx(), POLICY).passed


# --- end to end through the gate ---

def test_gate_downgrades_untrusted_retry_to_escalate_rather_than_denying():
    """Denying outright would throw away a recoverable payment because
    someone wrote text into a note field. The case still deserves a human."""
    decision = Gate(POLICY).evaluate(action(cited=("customer_note",)), ctx())
    assert decision.outcome == Outcome.MODIFY
    assert decision.final_action.action_type == ActionType.ESCALATE
    assert "untrusted_provenance" in decision.reason


def test_downgraded_action_carries_no_money_or_message_payload():
    decision = Gate(POLICY).evaluate(
        action(ActionType.NUDGE, cited=("customer_note",), message="pay now"), ctx()
    )
    assert decision.final_action.action_type == ActionType.ESCALATE
    assert decision.final_action.message is None
    assert decision.final_action.rail is None


def test_audit_trail_records_why_the_downgrade_happened():
    """The recorded provenance verdict must be the one judged on the
    PROPOSAL. Recording it against the rewritten ESCALATE would log the
    tautology that an escalation cites nothing dangerous, erasing the
    evidence."""
    decision = Gate(POLICY).evaluate(action(cited=("customer_note",)), ctx())
    entry = next(r for r in decision.rule_results if r.rule == "untrusted_provenance")
    assert entry.passed is False
    assert "customer_note" in entry.detail


def test_clean_retry_still_allowed_so_the_rule_is_not_just_refusing_everything():
    decision = Gate(POLICY).evaluate(action(cited=("reason", "attempts_so_far")), ctx())
    assert decision.outcome == Outcome.ALLOW
    assert decision.final_action.action_type == ActionType.RETRY


def test_a_harder_violation_still_denies_rather_than_downgrading():
    """Provenance downgrades; it does not launder an action that another
    invariant would have denied outright."""
    decision = Gate(POLICY).evaluate(
        action(cited=("customer_note",)), ctx(invoice_already_settled=True)
    )
    assert decision.outcome == Outcome.DENY


# --- persistence ---

def test_cited_fields_survive_a_serde_round_trip():
    """The audit trail is the evidence. Citations that don't persist can't
    be replayed, and an unreplayable claim isn't a claim."""
    a = action(cited=("reason", "customer_note"))
    assert action_from_dict(action_to_dict(a)).cited_fields == ("reason", "customer_note")
