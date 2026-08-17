from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from urllib.request import Request, urlopen

from server.manager import runtime as manager
from server.manager.http.visitor_access import (
    configured_public_visitor_login_allowlist,
)
from server.manager.storage.local_accounts import LocalAccountStore
from tools.data.account_manage import hash_password


class _AccountStore:
    def __init__(self, accounts: list[dict[str, object]]) -> None:
        self.accounts = accounts

    def load_accounts(self) -> list[dict[str, object]]:
        return [dict(item) for item in self.accounts]


@contextmanager
def _running_manager(state):
    manager.Handler.state = state
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _headers(*, cookie: str = "") -> dict[str, str]:
    headers = {
        "Host": "101.133.144.27:7998",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-For": "8.8.8.8",
        "Content-Type": "application/json",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _accounts() -> list[dict[str, object]]:
    test_a_salt = "test-a-salt"
    max_salt = "max-salt"
    return [
        {
            "username": "GTHT@testA@545963541963",
            "alias": "testA",
            "salt": test_a_salt,
            "hash": hash_password("visitor-password", test_a_salt),
            "role": "user",
            "is_admin": False,
            "organization_id": "GTHT",
            "active": True,
        },
        {
            "username": "GTHT@MaxJJW@392452984564",
            "alias": "MaxJJW",
            "salt": max_salt,
            "hash": hash_password("administrator-password", max_salt),
            "role": "super_admin",
            "is_admin": True,
            "organization_id": "GTHT",
            "active": True,
        },
    ]


def test_public_visitor_login_allowlist_is_explicit_and_case_sensitive() -> None:
    assert configured_public_visitor_login_allowlist(
        " testA,GTHT@testA@545963541963,testA,,"
    ) == ("testA", "GTHT@testA@545963541963")
    assert configured_public_visitor_login_allowlist("TestA") == ("TestA",)


def test_public_visitor_login_resolves_only_one_explicitly_allowlisted_account(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(manager, "control_store_from_env", lambda *_args: None)
    state = manager.ManagerState(tmp_path, "python", server_id="public-main")
    state.control_store = _AccountStore(_accounts())
    state.public_visitor_login_allowlist = ("testA", "MaxJJW")

    assert state.public_visitor_login_account("testA")["username"] == (
        "GTHT@testA@545963541963"
    )
    assert state.public_visitor_login_account("GTHT@testA")["alias"] == "testA"
    assert state.public_visitor_login_account(
        "GTHT@testA@545963541963"
    )["alias"] == "testA"
    assert state.public_visitor_login_account("TestA") is None
    assert state.public_visitor_login_account("MaxJJW")["username"] == (
        "GTHT@MaxJJW@392452984564"
    )
    assert state.public_visitor_login_account("MaxJJW")["role"] == "super_admin"


def test_public_visitor_password_login_clears_visitor_and_binds_origin(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", "1")
    monkeypatch.setenv("FACTORTESTER_REQUIRE_DEVICE_AUTH", "1")
    monkeypatch.setenv("FACTORTESTER_PUBLIC_SERVER", "1")
    monkeypatch.setattr(manager, "control_store_from_env", lambda *_args: None)
    monkeypatch.setattr(
        LocalAccountStore,
        "sync_pending",
        lambda _self, _store: {"synced": 0, "rejected": 0},
    )
    state = manager.ManagerState(tmp_path, "python", server_id="public-main")
    state.control_store = _AccountStore(_accounts())
    state.public_visitor_login_allowlist = ("testA",)
    origin = "https://101.133.144.27:7998"
    visitor_token = state.visitor_access.issue_session(origin)

    with _running_manager(state) as base_url:
        response = urlopen(Request(
            f"{base_url}/auth/login",
            data=json.dumps({
                "username": "testA",
                "password": "visitor-password",
            }).encode(),
            headers=_headers(cookie=f"ft-manager-visitor={visitor_token}"),
            method="POST",
        ))
        payload = json.loads(response.read())
        cookies = response.headers.get_all("Set-Cookie") or []

    assert payload["success"] is True
    assert payload["username"] == "GTHT@testA@545963541963"
    assert payload["role"] == "user"
    session_cookie = next(item for item in cookies if item.startswith("ft-manager-session="))
    session_token = session_cookie.split("=", 1)[1].split(";", 1)[0]
    assert any(
        item.startswith("ft-manager-visitor=; Max-Age=0;")
        for item in cookies
    )
    assert state.session_allows_device_origin(session_token, origin)
    assert not state.session_allows_device_origin(
        session_token, "https://another.example"
    )


def test_public_visitor_relationship_sets_test_a_as_max_parent() -> None:
    from scripts.configure_public_visitor_login import plan_relationship

    updated, summary = plan_relationship(_accounts())
    max_account = next(
        item for item in updated if item["alias"] == "MaxJJW"
    )
    test_a = next(item for item in updated if item["alias"] == "testA")

    assert summary["visitor_username"] == "GTHT@testA@545963541963"
    assert max_account["parent_username"] == "GTHT@testA@545963541963"
    assert test_a["role"] == "user"
    assert test_a["is_admin"] is False
