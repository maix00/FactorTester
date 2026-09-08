from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

from server.manager import runtime as manager
from server.manager.domain.devices import DeviceRegistry
from server.manager.http.device_routes import DeviceNetworkRoutesMixin
from server.manager.state.sessions import SessionStateMixin


class _CentralStore:
    def __init__(self, *, visitor_accounts=None, users=None, allowlist=None, devices=None):
        self.visitor_accounts = list(visitor_accounts or [])
        self.users = list(users or [])
        self.allowlist = list(allowlist or [])
        self.devices = list(devices or [])
        self.added = []
        self.removed = []

    def public_visitor_login_accounts(self, *, server_id):
        assert server_id == "public-main"
        return [dict(item) for item in self.visitor_accounts]

    def admin_account_directory(self):
        return [dict(item) for item in self.users]

    def load_accounts(self):
        return [dict(item) for item in self.users]

    def list_public_visitor_allowlist(self, *, server_id, include_disabled):
        assert server_id == "public-main"
        assert include_disabled is True
        return [dict(item) for item in self.allowlist]

    def list_devices(self, *, username="", include_disabled=True):
        assert username == ""
        assert include_disabled is True
        return [dict(item) for item in self.devices]

    def add_public_visitor_allowlist(self, *, server_id, username, created_by):
        value = {
            "server_id": server_id, "username": username, "enabled": True,
            "created_by": created_by,
        }
        self.added.append(value)
        return value

    def remove_public_visitor_allowlist(self, *, server_id, username):
        self.removed.append((server_id, username))
        return {"server_id": server_id, "username": username, "enabled": False}

    def revoke_device(self, device_id):
        return next(item for item in self.devices if item["device_id"] == device_id)


class _VisitorState(SessionStateMixin):
    def __init__(self, store):
        self.server_id = "public-main"
        self.control_store = store
        self.public_visitor_login_allowlist = ("stale-env-entry",)


def _ordinary(username="GTHT@testA@545963541963"):
    return {
        "username": username,
        "alias": "testA",
        "role": "user",
        "is_admin": False,
        "active": True,
        "organization_id": "GTHT",
    }


def test_central_allowlist_is_used_instead_of_old_environment_entries():
    state = _VisitorState(_CentralStore(visitor_accounts=[_ordinary()]))

    assert state.public_visitor_login_account("testA")["username"].startswith("GTHT@testA")
    assert state.public_visitor_login_account("stale-env-entry") is None


def test_empty_central_allowlist_fails_closed():
    state = _VisitorState(_CentralStore(visitor_accounts=[]))

    assert state.public_visitor_login_account("stale-env-entry") is None


class _DevicePolicyRoute(DeviceNetworkRoutesMixin):
    def __init__(self, state, token="visitor-token"):
        self.state = state
        self.token = token

    def _bearer_token(self):
        return self.token


class _DevicePolicyState:
    public_server = True

    def __init__(self, authentication="visitor-password", account=True):
        self.authentication = authentication
        self.account = account

    def session_authentication(self, token):
        return self.authentication

    def public_visitor_login_account(self, username):
        return _ordinary(username) if self.account else None


def test_only_live_allowlisted_visitor_sessions_can_enroll_devices():
    route = _DevicePolicyRoute(_DevicePolicyState())
    assert route._is_allowlisted_visitor_session({"username": "GTHT@testA@545963541963"}) is True

    route.state.authentication = "password"
    assert route._is_allowlisted_visitor_session({"username": "GTHT@testA@545963541963"}) is False

    route.state.authentication = "visitor-password"
    route.state.account = False
    assert route._is_allowlisted_visitor_session({"username": "GTHT@testA@545963541963"}) is False


def test_admin_access_control_is_super_admin_only_and_centralized(tmp_path, monkeypatch):
    monkeypatch.delenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", raising=False)
    store = _CentralStore(
        visitor_accounts=[_ordinary()],
        users=[_ordinary()],
        allowlist=[{
            "server_id": "public-main", "username": "GTHT@testA@545963541963",
            "alias": "testA", "enabled": True, "account_active": True,
        }],
        devices=[{
            "device_id": "device-test-123456",
            "public_key": {"kty": "EC", "crv": "P-256", "x": "x", "y": "y"},
            "username": "GTHT@testA@545963541963", "device_name": "Mac",
            "enabled": True, "public_access": True, "source_server_id": "public-main",
        }],
    )
    state = manager.ManagerState(tmp_path, "python", server_id="public-main")
    state.control_store = store
    state.device_registry = DeviceRegistry(
        tmp_path / "devices.json", server_id="public-main", control_store=store,
        public_server=True,
    )
    token = "admin-access-token"
    state._sessions[state._token_hash(token)] = (
        "GTHT@MaxJJW@392452984564", "super_admin", float("inf"),
    )
    manager.Handler.state = state
    server = ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/admin/access-control",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert payload["success"] is True
    assert payload["control_database"]["synchronized_across_managers"] is True
    assert payload["visitor_allowlist"][0]["username"].startswith("GTHT@testA")
    assert payload["devices"][0]["device_id"] == "device-test-123456"


def test_admin_allowlist_mutations_reject_other_server(tmp_path):
    # The route's current-server scope is tested by the store contract in the
    # HTTP layer; the central repository itself remains the cross-Manager sink.
    store = _CentralStore()
    state = _VisitorState(store)
    assert state.server_id == "public-main"


def test_allowlist_delete_stays_on_manager_and_checks_role_and_scope(tmp_path, monkeypatch):
    """The broad /api/admin proxy must never consume Manager policy deletes."""
    from urllib.error import HTTPError
    import pytest

    monkeypatch.delenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", raising=False)
    state = manager.ManagerState(tmp_path, "python", server_id="public-main")
    state.control_store = store = _CentralStore()
    state._sessions[state._token_hash("admin")] = ("admin", "super_admin", float("inf"))
    state._sessions[state._token_hash("user")] = ("testB", "user", float("inf"))

    class Handler(manager.Handler):
        def _proxy_authenticated_local_service(self, parsed, *, method):
            raise AssertionError("Manager allowlist must not reach service proxy")

    Handler.state = state
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def delete(token, **extra):
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/admin/public-visitor-allowlist",
            method="DELETE", data=json.dumps({"username": "testB", **extra}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urlopen(request) as response:
            return json.load(response)
    try:
        with pytest.raises(HTTPError) as failure:
            delete("user")
        assert failure.value.code == 403
        with pytest.raises(HTTPError) as failure:
            delete("admin", server_id="other-server")
        assert failure.value.code == 400
        assert store.removed == []
        assert delete("admin")["entry"]["enabled"] is False
        assert store.removed == [("public-main", "testB")]
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
