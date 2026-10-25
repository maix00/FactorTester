import pytest
from flask import Flask
from server.modules.single_factor_test import sft_bp


@pytest.fixture(autouse=True)
def _dual_mode(monkeypatch):
    monkeypatch.setenv("TRADERESEARCH_AUTH_MODE", "dual")


def _client():
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    return app.test_client()


def test_oidc_start_requires_configuration(monkeypatch):
    monkeypatch.delenv("TRADERESEARCH_KEYCLOAK_URL", raising=False)
    monkeypatch.delenv("FACTORTESTER_KEYCLOAK_URL", raising=False)
    response = _client().get("/api/auth/oidc/start")
    assert response.status_code == 503


def test_oidc_callback_rejects_bad_state():
    response = _client().get("/api/auth/oidc/callback?code=c&state=bad")
    assert response.status_code == 400


def test_oidc_callback_restores_legacy_username_and_role(monkeypatch):
    class Client:
        def __init__(self, *args, **kwargs): pass
        def exchange_code(self, code, redirect_uri): return {"access_token": "t"}

    class Adapter:
        def __init__(self, *args, **kwargs): pass
        def user(self, username):
            class I: attributes = {"legacy_username": ("GTHT@Alice",)}
            return I()

    monkeypatch.setattr("server.identity.keycloak.OIDCClient", Client)
    monkeypatch.setattr("server.identity.keycloak.oidc_userinfo", lambda **kwargs: {"preferred_username": "gtht@alice"})
    monkeypatch.setattr("server.identity.keycloak.KeycloakAdminAdapter", Adapter)
    monkeypatch.setenv("TRADERESEARCH_KEYCLOAK_URL", "http://kc")
    monkeypatch.setenv("TRADERESEARCH_KEYCLOAK_REALM", "trade")
    monkeypatch.setenv("TRADERESEARCH_KEYCLOAK_CLIENT_ID", "web")
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session: session["oidc_state"] = "s"
    response = client.get("/api/auth/oidc/callback?code=c&state=s")
    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session["username"] == "GTHT@Alice"


def test_oidc_logout_clears_session_and_redirects(monkeypatch):
    monkeypatch.setenv("TRADERESEARCH_KEYCLOAK_URL", "http://kc")
    monkeypatch.setenv("TRADERESEARCH_KEYCLOAK_REALM", "trade")
    monkeypatch.setenv("TRADERESEARCH_KEYCLOAK_CLIENT_ID", "web")
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session: session["username"] = "alice"
    response = client.get("/api/auth/oidc/logout")
    assert response.status_code == 302
    assert "/protocol/openid-connect/logout" in response.headers["Location"]
    with client.session_transaction() as session:
        assert "username" not in session
