"""Append-only audit trail — one record per gate decision. Thesis-critical:
this is what makes the safety claim verifiable rather than asserted. See
audit/replay.py for reconstructing a decision offline, without an LLM call.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    run_id: str
    strategy_name: str
    step: int
    order_id: str
    payment_id: str

    event: dict                    # domain.serde.event_to_dict of the order's first event
    context_snapshot: dict         # domain.serde.context_to_dict — full observable state at decision time
    diagnosis: dict                # {"reason", "confidence", "reasoning"} — from the proposer, agent or baseline
    proposed_action: dict          # domain.serde.action_to_dict of what was proposed

    rule_results: list[dict]       # every gate.rules invariant evaluated, and its result
    disposition: str               # ALLOW | DENY | MODIFY
    disposition_reason: str
    final_action: dict | None      # None on DENY

    execution_outcome: dict | None # from gate.executor.execute(), None if nothing executed
    money_delta: int               # paise moved as a result of this decision (0 if none)

    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AuditTrail:
    """Append-only. One JSONL file per run under runs/{run_id}/audit.jsonl."""

    def __init__(self, run_id: str, runs_dir: str = "runs"):
        self.run_id = run_id
        self.path = Path(runs_dir) / run_id / "audit.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: DecisionRecord) -> None:
        with open(self.path, "a") as f:
            f.write(json.dumps(asdict(record)) + "\n")

    def load_all(self) -> list[DecisionRecord]:
        if not self.path.exists():
            return []
        records = []
        with open(self.path) as f:
            for line in f:
                if line.strip():
                    records.append(DecisionRecord(**json.loads(line)))
        return records

    def get(self, decision_id: str) -> DecisionRecord | None:
        for r in self.load_all():
            if r.decision_id == decision_id:
                return r
        return None
