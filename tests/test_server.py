from fastapi.testclient import TestClient

from server import app, get_kibana_agent


class FakeKibanaAgent:
    async def check(self, check_name, alert):
        return {"finding": f"fake finding for {check_name}", "anomaly": True}


def test_collect_evidence_dispatches_kibana_requests():
    app.dependency_overrides[get_kibana_agent] = lambda: FakeKibanaAgent()
    client = TestClient(app)

    response = client.post("/api/v1/collect-evidence", json={
        "incident_id": "ALT-001",
        "alert": {"service": "payment-service"},
        "requests": [
            {"agent": "kibana", "check": "error_logs", "target_hypothesis": "H1"},
        ],
    })

    assert response.status_code == 200
    evidence = response.json()["evidence"]
    assert len(evidence) == 1
    assert evidence[0]["agent"] == "kibana"
    assert evidence[0]["check"] == "error_logs"
    assert evidence[0]["target_hypothesis"] == "H1"
    assert evidence[0]["anomaly"] is True
    app.dependency_overrides.clear()


def test_collect_evidence_returns_not_available_for_unwired_agents():
    app.dependency_overrides[get_kibana_agent] = lambda: FakeKibanaAgent()
    client = TestClient(app)

    response = client.post("/api/v1/collect-evidence", json={
        "incident_id": "ALT-001",
        "alert": {"service": "payment-service"},
        "requests": [
            {"agent": "grafana", "check": "cpu_usage", "target_hypothesis": "H1"},
        ],
    })

    assert response.status_code == 200
    evidence = response.json()["evidence"]
    assert evidence[0]["anomaly"] is False
    assert "not available" in evidence[0]["finding"].lower()
    app.dependency_overrides.clear()
