from flask import Flask
from server.modules.single_factor_test import sft_bp


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
