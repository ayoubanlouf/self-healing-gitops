from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data

def test_metrics_endpoint():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert b"http_requests_total" in response.content

def test_normal_workload_and_chaos_lifecycle():
    # 1. Normal workload
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    # 2. Inject chaos
    inject_resp = client.post("/chaos/inject")
    assert inject_resp.status_code == 200
    assert inject_resp.json()["status"] == "chaos_active"

    # 3. Workload under failure
    fail_resp = client.get("/")
    assert fail_resp.status_code == 500
    assert fail_resp.json()["status"] == "error"

    # 4. Reset chaos
    reset_resp = client.post("/chaos/reset")
    assert reset_resp.status_code == 200
    assert reset_resp.json()["status"] == "nominal"

    # 5. Workload restored
    recovered_resp = client.get("/")
    assert recovered_resp.status_code == 200
    assert recovered_resp.json()["status"] == "ok"
