"""Direct unit tests for api/security.py — the sanitizers themselves,
independent of whether the ASGI layer happens to normalize a given URL
before it reaches our route handlers."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.security import safe_data_dir, safe_id


def test_safe_id_accepts_generated_shapes():
    assert safe_id("run_B0_blind_retry_ff2f4c37a4", "run_id") == "run_B0_blind_retry_ff2f4c37a4"
    assert safe_id("dec_569adee997a2", "decision_id") == "dec_569adee997a2"


def test_safe_id_rejects_dotdot():
    with pytest.raises(HTTPException) as exc:
        safe_id("..", "run_id")
    assert exc.value.status_code == 400


def test_safe_id_rejects_path_separators():
    with pytest.raises(HTTPException):
        safe_id("../../etc/passwd", "run_id")
    with pytest.raises(HTTPException):
        safe_id("a/b", "run_id")


def test_safe_id_rejects_empty_and_overlong():
    with pytest.raises(HTTPException):
        safe_id("", "run_id")
    with pytest.raises(HTTPException):
        safe_id("a" * 129, "run_id")


def test_safe_data_dir_accepts_real_split():
    resolved = safe_data_dir("data/corpus")
    assert resolved.endswith("data/corpus")


def test_safe_data_dir_rejects_traversal_outside_data():
    with pytest.raises(HTTPException) as exc:
        safe_data_dir("../../../../etc")
    assert exc.value.status_code == 400


def test_safe_data_dir_rejects_absolute_path_outside_project():
    with pytest.raises(HTTPException):
        safe_data_dir("/etc/passwd")


def test_reading_a_nonexistent_run_does_not_create_it(tmp_path, monkeypatch):
    """A GET must not leave a directory behind for an id that doesn't exist —
    otherwise repeated reads with arbitrary ids grow the runs/ tree without
    bound."""
    from audit.trail import AuditTrail

    trail = AuditTrail("never_written_run", runs_dir=str(tmp_path))
    assert trail.load_all() == []
    assert trail.get("dec_nope") is None
    assert not (tmp_path / "never_written_run").exists()


def _sample_record():
    from audit.trail import DecisionRecord

    return DecisionRecord(
        decision_id="dec_1", run_id="written_run", strategy_name="test", step=0,
        order_id="o1", payment_id="p1", event={}, context_snapshot={},
        diagnosis={}, proposed_action={"action_type": "STOP"}, rule_results=[],
        disposition="ALLOW", disposition_reason="", final_action={"action_type": "STOP"},
        execution_outcome=None, money_delta=0,
    )


def test_appending_still_creates_the_run_directory(tmp_path):
    from audit.trail import AuditTrail

    trail = AuditTrail("written_run", runs_dir=str(tmp_path))
    assert not (tmp_path / "written_run").exists()
    trail.append(_sample_record())
    assert (tmp_path / "written_run" / "audit.jsonl").exists()
    assert len(trail.load_all()) == 1
