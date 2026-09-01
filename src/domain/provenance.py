"""Which context fields are system-of-record facts and which are free text
that a customer (or anyone who can write into a customer-visible field)
could have authored.

This is the data half of the project's prompt-injection claim. The gate
cannot tell whether a model "was manipulated" — that is not a decidable
question about a text string. What it *can* decide, deterministically, is
whether the agent's own stated justification for moving money rests on data
that an attacker could have written. That turns "the model should ignore
instructions in the note field" (a hope about behaviour) into "an action
justified by untrusted data cannot execute" (a property of the system).

Pure data + pure functions. Zero I/O, zero imports from other src/ packages,
so both agent/ (to enumerate what it may cite) and gate/ (to judge what it
did cite) can depend on this without depending on each other.
"""

from __future__ import annotations

# Facts written by the payments platform, the issuer, or the ledger. An
# attacker who can only supply customer-facing text cannot forge these.
TRUSTED_FIELDS = frozenset({
    # failure event, as reported by the gateway
    "reason", "rail", "amount", "occurred_at", "attempt_number", "mandate_id",
    # ledger / order state
    "now", "attempts_so_far", "mandate_presentations_so_far",
    "invoice_already_settled", "refund_in_flight", "open_chargeback",
    "last_contact_at", "amount_ceiling",
    # customer flags — set by risk/compliance systems, not by the customer
    "customer.do_not_contact", "customer.risk_flagged",
})

# Free text. `customer_note` is supplied by the customer outright; the others
# are fields that routinely carry customer- or merchant-authored strings
# (display names, order notes, payment descriptors) and reach us verbatim.
UNTRUSTED_FIELDS = frozenset({
    "customer_note", "customer.name", "order_notes", "gateway_message",
})

ALL_KNOWN_FIELDS = TRUSTED_FIELDS | UNTRUSTED_FIELDS


def is_untrusted(field: str) -> bool:
    """Unknown field names count as UNTRUSTED.

    Deliberately fail-closed: a hallucinated or newly-added field name we
    have not classified is exactly the case where we know least, so it must
    not be the one that silently gets treated as a system-of-record fact.
    The cost of being wrong here is an escalation; the cost of the opposite
    default is an unnoticed money movement justified by attacker text.
    """
    return field not in TRUSTED_FIELDS


def untrusted_citations(cited_fields) -> tuple[str, ...]:
    """The subset of `cited_fields` that may not justify a money action."""
    return tuple(f for f in (cited_fields or ()) if is_untrusted(f))
