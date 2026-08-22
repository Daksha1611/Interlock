"""End-to-end tests for the FastAPI surface, using the free baselines only
(no network, no API cost). Exercises the exact same code paths a live
/run agent call would, minus the LLM call itself."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    assert "/run" in r.json()["endpoints"]


def test_run_corpus_mode_b0():
    r = client.post("/run", json={"strategy": "B0", "data_dir": "data/corpus"})
    assert r.status_code == 200
    body = r.json()
    assert body["safety"]["policy_violations"] == 0
    assert body["strategy_name"] == "B0_blind_retry"


def test_run_redteam_mode_b1():
    r = client.post("/run", json={"strategy": "B1", "mode": "redteam", "n_replicates": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["total_cases"] == 10
    assert body["system_violation_count"] == 0


def test_run_unknown_data_dir_404s():
    r = client.post("/run", json={"strategy": "B0", "data_dir": "data/does_not_exist"})
    assert r.status_code == 404


def test_run_path_traversal_data_dir_rejected():
    r = client.post("/run", json={"strategy": "B0", "data_dir": "../../../../etc"})
    assert r.status_code == 400


def test_compare_path_traversal_data_dir_rejected():
    r = client.get("/compare", params={"data_dir": "../../../../etc"})
    assert r.status_code == 400


def test_runs_invalid_run_id_rejected():
    # a run_id containing characters outside the charset the system itself
    # generates (see audit/trail.py) is rejected before it reaches a path
    r = client.get("/runs/not@valid!id")
    assert r.status_code == 400


def test_audit_invalid_run_id_rejected():
    r = client.get("/audit/not@valid!id/dec_1")
    assert r.status_code == 400


def test_run_invalid_strategy_422s():
    r = client.post("/run", json={"strategy": "not_a_strategy"})
    assert r.status_code == 422  # pydantic Literal validation


def test_compare_and_runs_and_audit_roundtrip():
    r = client.get("/compare", params={"data_dir": "data/corpus"})
    assert r.status_code == 200
    reports = r.json()["reports"]
    assert {rep["strategy_name"] for rep in reports} == {"B0_blind_retry", "B1_scheduled_retry"}
    run_id = reports[0]["run_id"]

    r2 = client.get(f"/runs/{run_id}")
    assert r2.status_code == 200
    assert r2.json()["n_decisions"] > 0
    decision_id = r2.json()["decisions"][0]["decision_id"]

    r3 = client.get(f"/runs/{run_id}/{decision_id}")
    assert r3.status_code == 200
    assert r3.json()["decision_id"] == decision_id

    r4 = client.get(f"/audit/{run_id}/{decision_id}")
    assert r4.status_code == 200
    assert r4.json()["matches"] is True

    r5 = client.get(f"/audit/{run_id}")
    assert r5.status_code == 200
    assert r5.json()["fully_replayable"] is True


def test_runs_404_for_unknown_run_id():
    r = client.get("/runs/does_not_exist_12345")
    assert r.status_code == 404


def test_audit_404_for_unknown_decision():
    r = client.get("/audit/does_not_exist_12345/dec_nope")
    assert r.status_code == 404
