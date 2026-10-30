from __future__ import annotations

from flask import Flask, g

from server import auth


def _client(monkeypatch, *, identity=None):
    identity = identity or {
        "username": "alice",
        "alias": "Alice",
        "role": "user",
        "keycloak_roles": (),
        "keycloak_subject": "subject-alice",
    }
    monkeypatch.setattr(
        "server.services.session_runtime._keycloak_request_session",
        lambda: (g.__setattr__("keycloak_user_session", identity) or identity),
    )
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(auth.auth_bp)
    return app.test_client()


def _unauthenticated_client():
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(auth.auth_bp)

    @app.get("/api/private-probe")
    def private_probe():
        return {"success": True}

    return app.test_client()


def test_unauthenticated_api_get_returns_keycloak_login_required() -> None:
    response = _unauthenticated_client().get(
        "/api/private-probe", headers={"Accept": "application/json"},
    )

    assert response.status_code == 401
    assert response.content_type == "application/json"
    assert response.get_json() == {
        "success": False,
        "error": "请先通过 Keycloak 登录",
        "login_required": True,
    }


def test_unauthenticated_browser_get_is_json_without_service_page_redirect() -> None:
    response = _unauthenticated_client().get("/api/private-probe")

    assert response.status_code == 401
    assert response.content_type == "application/json"
    assert response.get_json()["login_required"] is True


def test_local_password_and_registration_routes_are_retired() -> None:
    client = _unauthenticated_client()
    requests = (
        client.post("/login", json={"username": "alice", "password": "password"}),
        client.post("/register", json={"username": "intruder", "password": "password"}),
        client.post("/api/account/password", json={
            "current_password": "password", "new_password": "new-password",
        }),
        client.get("/api/organizations"),
        client.post("/api/keep_login", json={"keep_login": True}),
    )

    assert all(response.status_code == 410 for response in requests)
    assert all(
        response.get_json()["code"] == "keycloak_managed_identity"
        for response in requests
    )


def test_api_me_returns_verified_keycloak_claims_without_local_account_lookup(
    monkeypatch,
) -> None:
    client = _client(monkeypatch, identity={
        "username": "alice",
        "alias": "Alice",
        "role": "super_admin",
        "keycloak_roles": ("admin_console:manage",),
        "keycloak_subject": "subject-alice",
    })

    response = client.get("/api/me")

    assert response.status_code == 200
    assert response.get_json() == {
        "username": "alice",
        "alias": "Alice",
        "role": "super_admin",
        "keycloak_roles": ["admin_console:manage"],
        "is_admin": True,
        "is_developer": False,
        "keep_login": False,
    }
