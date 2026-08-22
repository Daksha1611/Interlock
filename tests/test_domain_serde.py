"""context_from_dict must fail loudly on a truncated/corrupted audit record
rather than silently reconstruct a falsely-safe Context. Found by code
review: a missing `open_chargeback` (say, from a partial write during a
crash) used to default to False, which could replay a correctly-DENIED
decision as ALLOW."""

from __future__ import annotations

from datetime import datetime

import pytest

from domain.context import Context
from domain.customer import Customer
from domain.serde import context_from_dict, context_to_dict

FULL = context_to_dict(
    Context(
        now=datetime(2026, 7, 1),
        customer=Customer(customer_id="c1", name="Test"),
        attempts_so_far=1,
        mandate_presentations_so_far=0,
        invoice_already_settled=False,
        refund_in_flight=False,
        open_chargeback=True,
        amount=1000,
        extra={"risk_flagged": True},
    )
)


def test_full_record_round_trips():
    ctx = context_from_dict(FULL)
    assert ctx.open_chargeback is True
    assert ctx.extra == {"risk_flagged": True}


@pytest.mark.parametrize(
    "missing_key",
    [
        "attempts_so_far",
        "mandate_presentations_so_far",
        "invoice_already_settled",
        "refund_in_flight",
        "open_chargeback",
        "amount",
        "extra",
    ],
)
def test_missing_safety_field_raises_instead_of_defaulting(missing_key):
    truncated = dict(FULL)
    del truncated[missing_key]
    with pytest.raises(KeyError):
        context_from_dict(truncated)


def test_missing_optional_field_still_defaults():
    truncated = dict(FULL)
    del truncated["last_failure_reason"]
    del truncated["amount_ceiling"]
    ctx = context_from_dict(truncated)
    assert ctx.last_failure_reason is None
    assert ctx.amount_ceiling is None
