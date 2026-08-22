"""Finds one good example of each disposition (ALLOW, DENY, MODIFY) in a run
and replays each offline, for the pitch's live audit-replay demo (§5, §11
item 4 of the spec). Run after any harness/redteam run that used AuditTrail.

    PYTHONPATH=src python -m audit.demo <run_id>
"""

from __future__ import annotations

import sys

from audit.replay import replay_decision
from audit.trail import AuditTrail


def find_examples(run_id: str) -> dict:
    trail = AuditTrail(run_id)
    records = trail.load_all()
    examples = {}
    for r in records:
        if r.disposition not in examples:
            examples[r.disposition] = r
        if len(examples) == 3:
            break
    return examples


def main():
    if len(sys.argv) != 2:
        print("usage: python -m audit.demo <run_id>")
        sys.exit(1)
    run_id = sys.argv[1]

    examples = find_examples(run_id)
    if not examples:
        print(f"no decisions found in run {run_id!r}")
        sys.exit(1)

    for disposition, record in examples.items():
        print(f"\n{'=' * 70}")
        print(f"{disposition}  —  decision_id={record.decision_id}  order={record.order_id}")
        print(f"{'=' * 70}")
        print(f"  proposed action : {record.proposed_action['action_type']}  "
              f"(diagnosed_reason={record.diagnosis.get('reason')}, confidence={record.diagnosis.get('confidence')})")
        print(f"  reasoning       : {record.diagnosis.get('reasoning', '')[:160]}")
        print(f"  gate reason     : {record.disposition_reason}")
        if record.final_action:
            print(f"  final action    : {record.final_action['action_type']} at {record.final_action['scheduled_at']}")

        result = replay_decision(run_id, record.decision_id)
        status = "MATCH — reconstructed offline, no LLM call" if result.matches else "MISMATCH (!)"
        print(f"  replay          : {result.replayed_disposition}  [{status}]")


if __name__ == "__main__":
    main()
