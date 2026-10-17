from fastapi.testclient import TestClient

from app.main import app


def test_whatsapp_approval_router_is_not_mounted():
    response = TestClient(app).post("/aprobar/generar", json={})
    assert response.status_code == 404
