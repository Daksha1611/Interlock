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
