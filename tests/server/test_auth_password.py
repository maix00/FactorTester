from __future__ import annotations

from copy import deepcopy

from flask import Flask

from server import auth
from tools.data.account_manage import hash_password, verify_password


def _client(monkeypatch):
    salt = "old-salt"
    accounts = [{
        "username": "default$MaxA@1",
        "alias": "MaxA",
        "salt": salt,
        "hash": hash_password("old-password", salt),
    }]
    saved = []
    monkeypatch.setattr(auth, "load_accounts", lambda: deepcopy(accounts))
    monkeypatch.setattr(auth, "save_accounts", lambda value: saved.append(deepcopy(value)))
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(auth.auth_bp)
    client = app.test_client()
    with client.session_transaction() as current:
        current["username"] = "default$MaxA@1"
    return client, saved


def _unauthenticated_client():
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(auth.auth_bp)

    @app.get("/api/private-probe")
    def private_probe():
        return {"success": True}

    return app.test_client()


def test_unauthenticated_api_get_returns_json_instead_of_login_html() -> None:
    response = _unauthenticated_client().get(
        "/api/private-probe",
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 401
    assert response.content_type == "application/json"
    assert response.get_json() == {
        "success": False,
        "error": "请先登录",
        "login_required": True,
    }


def test_unauthenticated_browser_get_is_json_without_service_page_redirect() -> None:
    response = _unauthenticated_client().get("/api/private-probe")

    assert response.status_code == 401
    assert response.content_type == "application/json"
    assert response.get_json()["login_required"] is True


def test_login_applies_explicit_persistent_session_atomically(
    monkeypatch,
) -> None:
    salt = "login-salt"
    accounts = [{
        "username": "default$MaxA@1",
        "alias": "MaxA",
        "salt": salt,
        "hash": hash_password("password", salt),
    }]
    monkeypatch.setattr(auth, "load_accounts", lambda: deepcopy(accounts))
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(auth.auth_bp)
    client = app.test_client()

    response = client.post(
        "/login",
        json={
            "username": "MaxA",
            "password": "password",
            "keep_login": True,
        },
    )

    assert response.status_code == 200
    assert client.get("/api/me").get_json()["keep_login"] is True


def test_login_without_explicit_persistence_remains_temporary(
    monkeypatch,
) -> None:
    salt = "login-salt"
    accounts = [{
        "username": "default$MaxA@1",
        "alias": "MaxA",
        "salt": salt,
        "hash": hash_password("password", salt),
    }]
    monkeypatch.setattr(auth, "load_accounts", lambda: deepcopy(accounts))
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(auth.auth_bp)
    client = app.test_client()

    response = client.post(
        "/login",
        json={"username": "MaxA", "password": "password"},
    )

    assert response.status_code == 200
    assert client.get("/api/me").get_json()["keep_login"] is False


def test_current_account_can_change_password(monkeypatch) -> None:
    client, saved = _client(monkeypatch)

    response = client.post(
        "/api/account/password",
        json={
            "current_password": "old-password",
            "new_password": "new-password",
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {"success": True}
    assert len(saved) == 1
    account = saved[0][0]
    assert verify_password("new-password", account["salt"], account["hash"])
    assert not verify_password("old-password", account["salt"], account["hash"])


def test_change_password_rejects_wrong_current_password(monkeypatch) -> None:
    client, saved = _client(monkeypatch)

    response = client.post(
        "/api/account/password",
        json={
            "current_password": "wrong-password",
            "new_password": "new-password",
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "当前密码错误"
    assert saved == []
