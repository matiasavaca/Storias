from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.routers.auth import _make_jwt


def test_portal_page_redirects_anonymous_employee_to_login():
    response = TestClient(app).get("/portal", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/login"


def test_portal_page_renders_authenticated_employee_shell():
    token = _make_jwt({
        "sub": "emp-1", "email": "pm@example.com", "name": "PM",
        "agency_id": "agency-1", "role": "employee",
    })
    response = TestClient(app).get("/portal", cookies={"session": token})

    assert response.status_code == 200
    assert 'id="client-list"' in response.text
    assert 'id="business-description"' in response.text
    assert 'id="weekly-focus"' in response.text
    assert "Enfoque semanal" in response.text
    assert "pm@example.com" not in response.text
    assert "agency-1" not in response.text
    assert '<script src="/static/portal.js" defer></script>' in response.text


def test_portal_frontend_uses_real_api_without_prototype_data():
    response = TestClient(app).get("/static/portal.js")

    assert response.status_code == 200
    source = response.text
    assert "api(`/portal/clientes" in source
    assert "/probar-prompt" in source
    assert "PATCH" in source
    assert "DELETE" in source
    assert "/portal/historias/reordenar" in source
    assert "response.status === 401" in source
    assert "response.status === 403" in source
    assert "credentials: 'same-origin'" in source
    assert "selectionVersion" in source
    assert "clientId !== state.client?.id" in source
    assert "state.client = null" in source
    assert "CUAN Arquitectura" not in source
    assert "Panadería Dora" not in source
    assert "images.unsplash.com" not in source


def test_static_assets_are_never_cached_in_development():
    # portal.js/portal.html change every few minutes during dev and are
    # served fresh from disk under the same URL every time — without this,
    # a browser can keep running a stale cached copy after an edit.
    response = TestClient(app).get("/static/portal.js")

    assert response.headers.get("cache-control") == "no-store"


def test_engine_fonts_are_served_read_only_for_the_font_previews():
    # Same files app.engine.imaging composes with server-side, exposed
    # so the portal's typography pickers can preview each option live.
    response = TestClient(app).get("/fonts/Raleway%5Bwght%5D.ttf")

    assert response.status_code == 200
    assert response.headers["content-type"] in ("font/ttf", "application/font-sfnt", "application/octet-stream")
