"""Corpus generator. Produces the observable events (what strategies see)
and the hidden ground truth (what the world simulator uses to resolve
outcomes). Freeze the output before writing any strategy — re-running this
with the same seed must reproduce byte-identical corpora.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import yaml

from domain.customer import Customer
from domain.events import PaymentEvent
from domain.serde import customer_to_dict, event_to_dict
from generator.customers import build_customers
from generator.distributions import (
    MANDATE_REASONS,
    bernoulli,
    sample_amount,
    sample_rail,
    sample_reason,
)
from world.ledger import OrderGroundTruth, ground_truth_to_dict

SIM_START = datetime(2026, 7, 1, 0, 0, 0)
SPREAD_DAYS = 30


def _load(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _maybe_at(rng: np.random.Generator, base: datetime, prob: float, lo_h: float, hi_h: float) -> datetime | None:
    if not bernoulli(rng, prob):
        return None
    return base + timedelta(hours=float(rng.uniform(lo_h, hi_h)))


def build(
    config_dir: str = "config",
    data_dir: str = "data",
    seed_override: int | None = None,
) -> dict:
    sim_cfg = _load(f"{config_dir}/simulation.yaml")
    taxonomy = _load(f"{config_dir}/taxonomy.yaml")
    seed = seed_override if seed_override is not None else sim_cfg["seed"]
    rng = np.random.default_rng(seed)

    customers = build_customers(rng, sim_cfg)
    bg = sim_cfg["background"]

    events: list[PaymentEvent] = []
    truths: list[OrderGroundTruth] = []

    for i in range(sim_cfg["corpus_size"]):
        customer = customers[rng.integers(0, len(customers))]
        reason = sample_reason(rng, taxonomy)
        rail = sample_rail(rng, reason)
        amount = sample_amount(rng, sim_cfg["amount"])
        occurred_at = SIM_START + timedelta(hours=float(rng.uniform(0, SPREAD_DAYS * 24)))

        order_id = f"order_{i:06d}"
        payment_id = f"pay_{i:06d}"
        mandate_id = f"mandate_{i:06d}" if reason in MANDATE_REASONS else None

        already_succeeded_prob = taxonomy["reasons"][reason.value].get("already_succeeded_prob", 0.0)
        already_succeeded = bernoulli(rng, already_succeeded_prob)

        external_settlement_at = None
        if not already_succeeded:
            external_settlement_at = _maybe_at(rng, occurred_at, bg["external_settlement_prob"], 6, 96)

        refund_in_flight_at = _maybe_at(rng, occurred_at, bg["refund_in_flight_prob"], 1, 48)
        open_chargeback_at = _maybe_at(rng, occurred_at, bg["open_chargeback_prob"], 24, 240)
        risk_flagged_at = _maybe_at(rng, occurred_at, bg["post_failure_risk_flag_prob"], 1, 72)
        dnc_added_at = _maybe_at(rng, occurred_at, bg["dnc_added_mid_sequence_prob"], 1, 72)
        duplicate_webhook = bernoulli(rng, bg["duplicate_webhook_prob"])

        events.append(
            PaymentEvent(
                event_id=f"evt_{i:06d}_a",
                payment_id=payment_id,
                order_id=order_id,
                customer_id=customer.customer_id,
                amount=amount,
                currency="INR",
                rail=rail,
                reason=reason,
                occurred_at=occurred_at,
                attempt_number=1,
                mandate_id=mandate_id,
            )
        )
        if duplicate_webhook:
            events.append(
                PaymentEvent(
                    event_id=f"evt_{i:06d}_b",
                    payment_id=payment_id,
                    order_id=order_id,
                    customer_id=customer.customer_id,
                    amount=amount,
                    currency="INR",
                    rail=rail,
                    reason=reason,
                    occurred_at=occurred_at + timedelta(minutes=2),
                    attempt_number=1,
                    mandate_id=mandate_id,
                )
            )

        truths.append(
            OrderGroundTruth(
                order_id=order_id,
                payment_id=payment_id,
                customer_id=customer.customer_id,
                amount=amount,
                rail=rail.value,
                reason=reason.value,
                first_failure_at=occurred_at,
                mandate_id=mandate_id,
                already_succeeded=already_succeeded,
                external_settlement_at=external_settlement_at,
                refund_in_flight_at=refund_in_flight_at,
                refund_window_hours=bg["refund_window_hours"],
                open_chargeback_at=open_chargeback_at,
                risk_flagged_at=risk_flagged_at,
                dnc_added_at=dnc_added_at,
                duplicate_webhook=duplicate_webhook,
            )
        )

    order_ids = [t.order_id for t in truths]
    idx = np.arange(len(order_ids))
    rng.shuffle(idx)
    n_holdout = int(len(idx) * sim_cfg["holdout_fraction"])
    holdout_ids = set(order_ids[i] for i in idx[:n_holdout])

    train_events = [e for e in events if e.order_id not in holdout_ids]
    holdout_events = [e for e in events if e.order_id in holdout_ids]
    train_truths = [t for t in truths if t.order_id not in holdout_ids]
    holdout_truths = [t for t in truths if t.order_id in holdout_ids]

    _write_split(f"{data_dir}/corpus", train_events, train_truths, customers)
    _write_split(f"{data_dir}/holdout", holdout_events, holdout_truths, customers)

    manifest = {
        "seed": seed,
        "corpus_size": sim_cfg["corpus_size"],
        "n_orders": len(truths),
        "n_train_orders": len(train_truths),
        "n_holdout_orders": len(holdout_truths),
        "n_train_events": len(train_events),
        "n_holdout_events": len(holdout_events),
        "n_customers": len(customers),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    Path(f"{data_dir}/corpus/manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def _write_split(
    out_dir: str, events: list[PaymentEvent], truths: list[OrderGroundTruth], customers: list[Customer]
) -> None:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    with open(f"{out_dir}/events.jsonl", "w") as f:
        for e in sorted(events, key=lambda e: e.occurred_at):
            f.write(json.dumps(event_to_dict(e)) + "\n")
    with open(f"{out_dir}/ground_truth.jsonl", "w") as f:
        for t in truths:
            f.write(json.dumps(ground_truth_to_dict(t)) + "\n")
    with open(f"{out_dir}/customers.jsonl", "w") as f:
        for c in customers:
            f.write(json.dumps(customer_to_dict(c)) + "\n")


if __name__ == "__main__":
    manifest = build()
    print(json.dumps(manifest, indent=2))
