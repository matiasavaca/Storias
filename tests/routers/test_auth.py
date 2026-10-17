from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.routers import auth


def _settings(*, environment: str = "development") -> Settings:
    return Settings(
        environment=environment,
        secret_key="test-secret",
        supabase_url="https://example.supabase.co",
        supabase_anon_key="anon",
        supabase_service_role_key="service-role",
        google_client_id="google-client",
        google_client_secret="google-secret",
        google_redirect_uri="http://localhost:5001/auth/callback",
        anthropic_api_key="anthropic",
        encryption_key="test-encryption-key",
    )


def test_canonical_authority_returns_redirect_uri_netloc():
    assert auth._canonical_authority(_settings()) == "localhost:5001"


def test_google_login_redirects_to_canonical_host_before_starting_oauth(monkeypatch):
    oauth_started = False

    class UnexpectedOAuthClient:
        def __init__(self, **kwargs):
            nonlocal oauth_started
            oauth_started = True

    monkeypatch.setattr(auth, "get_settings", _settings)
    monkeypatch.setattr(auth, "AsyncOAuth2Client", UnexpectedOAuthClient)

    response = TestClient(app).get(
        "http://127.0.0.1:5001/auth/google?next=%2Fportal%3Ftab%3Dweek",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == (
        "http://localhost:5001/auth/google?next=%2Fportal%3Ftab%3Dweek"
    )
    assert oauth_started is False


def test_google_login_starts_oauth_without_extra_redirect_on_canonical_host(monkeypatch):
    class FakeOAuthClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def create_authorization_url(self, url: str, **kwargs):
            assert self.kwargs["redirect_uri"] == "http://localhost:5001/auth/callback"
            assert kwargs["state"]
            return "https://accounts.google.test/authorize", kwargs["state"]

    monkeypatch.setattr(auth, "get_settings", _settings)
    monkeypatch.setattr(auth, "AsyncOAuth2Client", FakeOAuthClient)

    response = TestClient(app).get(
        "http://localhost:5001/auth/google",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == "https://accounts.google.test/authorize"
    assert "oauth_session=" in response.headers["set-cookie"]


def test_google_login_does_not_canonicalize_host_in_production(monkeypatch):
    class FakeOAuthClient:
        def __init__(self, **kwargs):
            pass

        def create_authorization_url(self, url: str, **kwargs):
            return "https://accounts.google.test/authorize", kwargs["state"]

    monkeypatch.setattr(auth, "get_settings", lambda: _settings(environment="production"))
    monkeypatch.setattr(auth, "AsyncOAuth2Client", FakeOAuthClient)

    response = TestClient(app).get(
        "http://127.0.0.1:5001/auth/google",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == "https://accounts.google.test/authorize"


def test_google_callback_logs_missing_session_state(monkeypatch, caplog):
    monkeypatch.setattr(auth, "get_settings", _settings)

    with caplog.at_level(logging.WARNING, logger=auth.__name__):
        response = TestClient(app).get(
            "http://localhost:5001/auth/callback?code=code&state=received",
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "State inválido — posible CSRF"}
    assert "callback sin oauth_state en sesión" in caplog.text
    assert "state mismatch" not in caplog.text


def test_google_callback_logs_mismatched_session_state(monkeypatch, caplog):
    monkeypatch.setattr(auth, "get_settings", _settings)
    monkeypatch.setattr(auth.secrets, "token_urlsafe", lambda _: "expected-state")

    with TestClient(app, base_url="http://localhost:5001") as client:
        login_response = client.get("/auth/google", follow_redirects=False)
        assert login_response.status_code == 307

        with caplog.at_level(logging.WARNING, logger=auth.__name__):
            response = client.get(
                "/auth/callback?code=code&state=received-state",
            )

    assert response.status_code == 400
    assert response.json() == {"detail": "State inválido — posible CSRF"}
    assert "OAuth state mismatch" in caplog.text
    assert "callback sin oauth_state en sesión" not in caplog.text
