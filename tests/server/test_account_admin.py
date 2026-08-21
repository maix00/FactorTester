from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from server.manager import runtime as manager
from server.manager.services import account_admin


class _DirectoryStore:
    def __init__(self):
        self.accounts = [{
            "username": "GTHT@MaxJJW@392452984564",
            "alias": "MaxJJW",
            "salt": "salt",
            "hash": "secret",
            "role": "super_admin",
            "is_admin": True,
            "is_developer": False,
            "organization_id": "GTHT",
            "organization_name": "GTHT",
            "level_id": "GTHT__ROOT",
            "parent_username": "",
            "active": True,
        }]
        self.organizations = [{"id": "GTHT", "name": "GTHT", "description": ""}]
        self.levels = [{
            "id": "GTHT__ROOT", "organization_id": "GTHT",
            "name": "默认层级", "parent_level_id": "", "manager_username": "",
        }]

    def admin_account_directory(self):
        return [dict(item) for item in self.accounts]

    def load_accounts(self):
        return [dict(item) for item in self.accounts if item.get("active", True)]

    def create_account(self, account):
        self.accounts.append(dict(account))

    def replace_accounts(self, accounts):
        self.accounts = [dict(item) for item in accounts]

    def load_organizations(self):
        return [dict(item) for item in self.organizations]

    def replace_organizations(self, organizations):
        self.organizations = [dict(item) for item in organizations]

    def load_levels(self):
        return [dict(item) for item in self.levels]

    def replace_levels(self, levels):
        self.levels = [dict(item) for item in levels]


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


def _state(tmp_path, store):
    state = manager.ManagerState(
        tmp_path, "python", server_id="public-main", state_root=tmp_path / "state",
    )
    state.control_store = store
    state.public_server = False
    state.require_login_for_ui = False
    state._sessions[state._token_hash("admin-token")] = (
        "GTHT@MaxJJW@392452984564", "super_admin", float("inf"),
    )
    return state


def test_account_directory_create_and_update_mirrors_local(monkeypatch):
    store = _DirectoryStore()
    mirrored = {}
    monkeypatch.setattr(account_admin, "save_accounts", lambda value: mirrored.setdefault("accounts", value))
    monkeypatch.setattr(account_admin, "save_organizations", lambda value: mirrored.setdefault("organizations", value))
    monkeypatch.setattr(account_admin, "save_levels", lambda value: mirrored.setdefault("levels", value))
    service = account_admin.AccountAdministrationService(store)

    created = service.create_user({
        "alias": "testA", "password": "secret1", "organization_id": "GTHT",
        "role": "user", "level_id": "GTHT__ROOT",
    })
    assert created["username"].startswith("GTHT@testA@")
    assert "hash" not in created
    service.update_user(
        created["username"],
        {"organization_id": "GTHT", "level_id": "GTHT__ROOT", "role": "developer"},
        current_username="GTHT@MaxJJW@392452984564",
    )
    assert store.accounts[-1]["role"] == "developer"
    assert mirrored["accounts"][-1]["username"] == created["username"]


def test_account_directory_create_initializes_reserved_self_profile(monkeypatch):
    store = _DirectoryStore()
    initialized = []
    monkeypatch.setattr(account_admin, "save_accounts", lambda value: None)
    monkeypatch.setattr(account_admin, "save_organizations", lambda value: None)
    monkeypatch.setattr(account_admin, "save_levels", lambda value: None)
    service = account_admin.AccountAdministrationService(
        store,
        profile_initializer=initialized.append,
    )

    created = service.create_user({
        "alias": "testA", "password": "secret1", "organization_id": "GTHT",
        "role": "user", "level_id": "GTHT__ROOT",
    })

    assert initialized == [created["username"]]


def test_account_directory_http_is_super_admin_only(tmp_path, monkeypatch):
    monkeypatch.setattr(account_admin, "save_accounts", lambda value: None)
    monkeypatch.setattr(account_admin, "save_organizations", lambda value: None)
    monkeypatch.setattr(account_admin, "save_levels", lambda value: None)
    state = _state(tmp_path, _DirectoryStore())
    token = "admin-token"
    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/api/admin/account-directory",
            headers={"Authorization": f"Bearer {token}", "X-Forwarded-Proto": "https"},
        )
        with urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
    assert payload["success"] is True
    assert payload["users"][0]["alias"] == "MaxJJW"
    assert "hash" not in payload["users"][0]
    assert payload["control_database"]["local_sqlite_mirror"] is True


def test_account_directory_serializes_postgres_timestamps(tmp_path, monkeypatch):
    monkeypatch.setattr(account_admin, "save_accounts", lambda value: None)
    monkeypatch.setattr(account_admin, "save_organizations", lambda value: None)
    monkeypatch.setattr(account_admin, "save_levels", lambda value: None)
    store = _DirectoryStore()
    timestamp = datetime(2026, 8, 17, 15, 45, tzinfo=timezone.utc)
    store.accounts[0]["created_at"] = timestamp
    store.accounts[0]["updated_at"] = timestamp
    store.organizations[0]["updated_at"] = timestamp
    store.levels[0]["updated_at"] = timestamp

    value = account_admin.AccountAdministrationService(store).snapshot()
    encoded = json.dumps(value, ensure_ascii=False)

    assert "2026-08-17T15:45:00+00:00" in encoded
