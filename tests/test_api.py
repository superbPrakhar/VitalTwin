"""End-to-end API tests via FastAPI TestClient (fresh in-memory store)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest                                                    # noqa: E402
from fastapi.testclient import TestClient                        # noqa: E402
from app.main import app                                         # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health_and_model_card(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    r = client.get("/api/model")
    assert r.status_code == 200
    assert "features" in r.json()


def test_patient_listing(client):
    r = client.get("/api/patients")
    assert r.status_code == 200
    pts = r.json()
    assert {p["patient_id"] for p in pts} == {"ravi", "meera", "arjun"}
    for p in pts:
        assert "risk_probability" in p and "hba1c_est" in p


def test_mirror_and_trends(client):
    r = client.get("/api/patients/ravi/mirror")
    assert r.status_code == 200
    body = r.json()
    assert body["organ_status"] and body["latest_estimate"].get("hr")
    r = client.get("/api/patients/ravi/trends?days=14")
    assert r.status_code == 200 and len(r.json()["summaries"]) <= 14
    r = client.get("/api/patients/ravi/hourly?hours=24")
    assert r.status_code == 200 and len(r.json()["records"]) == 24


def test_risk_includes_news2_twinrisk_and_alarms(client):
    r = client.get("/api/patients/arjun/risk")
    assert r.status_code == 200
    body = r.json()
    assert "score" in body["news2"]
    assert 0 <= body["twinrisk"]["probability"] <= 1
    assert isinstance(body["live_alarms"], list)
    assert isinstance(body["history"], list)


def test_alerts_and_unknown_patient(client):
    r = client.get("/api/patients/arjun/alerts")
    assert r.status_code == 200
    assert client.get("/api/patients/nope/risk").status_code == 404


def test_sync_advances_time(client):
    before = client.get("/api/patients/meera").json()["sync"]["last_t"]
    r = client.post("/api/patients/meera/sync", json={"hours": 6})
    assert r.status_code == 200
    after = client.get("/api/patients/meera").json()["sync"]["last_t"]
    assert after == before + 6


def test_simulate_goal_explain(client):
    r = client.post("/api/patients/ravi/simulate",
                    json={"scenario": {"steps_day": 9000, "kcal_delta_day": -250},
                          "horizon_days": 90})
    assert r.status_code == 200
    assert "deltas" in r.json()
    r = client.post("/api/patients/ravi/goal",
                    json={"lever": "metformin_mg", "target_metric": "hba1c_end",
                          "target_value": 7.0, "horizon_days": 90,
                          "scenario_base": {"steps_day": 9000, "kcal_delta_day": -250}})
    assert r.status_code == 200
    assert r.json()["feasible"]
    r = client.post("/api/patients/ravi/explain",
                    json={"scenario": {"carbs_day": 150}, "horizon_days": 60})
    assert r.status_code == 200 and r.json()["contributions"]
    # validation: unknown lever rejected
    r = client.post("/api/patients/ravi/simulate",
                    json={"scenario": {"not_a_lever": 1}, "horizon_days": 30})
    assert r.status_code == 422


def test_report_endpoint(client):
    r = client.get("/api/patients/meera/report")
    assert r.status_code == 200
    assert "VitalTwin clinical summary" in r.json()["markdown"]


def test_frontend_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "VitalTwin" in r.text
