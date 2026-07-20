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
