from flask import Flask

from server.modules.single_factor_test import sft_bp


def test_legacy_flask_oidc_endpoints_cannot_create_a_second_session():
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()

    for path in (
        "/api/auth/oidc/start",
        "/api/auth/oidc/callback?code=code&state=state",
        "/api/auth/oidc/logout",
    ):
        response = client.get(path)
        assert response.status_code == 410
        assert response.json["code"] == "manager_oidc_required"
