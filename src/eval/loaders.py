"""Load a generated corpus split (events + ground truth + customers) and the
config files every run needs. Shared by eval/report.py, redteam runs, and
the API layer."""

from __future__ import annotations

import json

import yaml

from domain.customer import Customer
from domain.events import PaymentEvent
from domain.serde import customer_from_dict, event_from_dict
from world.ledger import OrderGroundTruth, ground_truth_from_dict


def load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_jsonl(path: str) -> list[dict]:
    out = []
    with open(path) as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def load_split(
    data_dir: str, limit_orders: int | None = None, seed: int = 20260822
) -> tuple[list[PaymentEvent], list[OrderGroundTruth], list[Customer]]:
    """`limit_orders` deterministically subsamples to N orders (same seed ->
    same subset) — used to keep a live-LLM run within a free-tier API
    budget without touching the corpus itself. B0/B1 never need this."""
    events = [event_from_dict(d) for d in load_jsonl(f"{data_dir}/events.jsonl")]
    ground_truths = [ground_truth_from_dict(d) for d in load_jsonl(f"{data_dir}/ground_truth.jsonl")]
    customers = [customer_from_dict(d) for d in load_jsonl(f"{data_dir}/customers.jsonl")]

    if limit_orders is not None and limit_orders < len(ground_truths):
        import numpy as np

        rng = np.random.default_rng(seed)
        order_ids = sorted({t.order_id for t in ground_truths})
        chosen = set(rng.choice(order_ids, size=limit_orders, replace=False))
        events = [e for e in events if e.order_id in chosen]
        ground_truths = [t for t in ground_truths if t.order_id in chosen]

    return events, ground_truths, customers


def load_configs(config_dir: str = "config") -> dict:
    return {
        "policy": load_yaml(f"{config_dir}/policy.yaml"),
        "economics": load_yaml(f"{config_dir}/economics.yaml"),
        "taxonomy": load_yaml(f"{config_dir}/taxonomy.yaml"),
        "simulation": load_yaml(f"{config_dir}/simulation.yaml"),
    }
