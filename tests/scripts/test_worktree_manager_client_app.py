from __future__ import annotations

import inspect
import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest

from server.manager import runtime as manager
from server.manager.http import catalog_routes
from server.manager.http.job_proxy_routes import _SERVICE_WRITE_PATTERNS
from server.manager.services.client_state import ClientStateService
from server.manager.services.factor_source_hydration import FactorSourceHydrator
from server.manager.services.test_authoring import (
    TestAuthoringResponse as _TestAuthoringResponse,
)
from server.manager.services.test_authoring import (
    TestAuthoringService,
)
from server.manager.storage.control_db import ControlDatabaseUnavailable
from server.manager.storage.local_accounts import LocalAccountStore
from server.manager.storage.preferences import UserPreferenceStore
from server.manager.web import assets as research_static
from server.modules.custom_factors import factor_set_registry
from server.services.factor_source_catalog import FactorSourceCatalog
from server.services.factor_source_manifest import FactorSourceManifest
from server.services import research_configurations
from tools.data.account_manage import hash_password

ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def running_manager(state):
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


def authenticated_state(tmp_path):
    state = manager.ManagerState(
        tmp_path,
        "python",
        session_db_path=tmp_path / "manager-sessions.sqlite",
    )
    state._sessions[state._token_hash("user-token")] = (
        "user@1", "user", float("inf"),
    )
    return state


def _offline_account(password: str = "secret") -> dict[str, object]:
    salt = "offline-test-salt"
    return {
        "username": "GTHT@alice@1",
        "alias": "alice",
        "salt": salt,
        "hash": hash_password(password, salt),
        "role": "user",
        "is_admin": False,
        "is_developer": False,
        "organization_id": "GTHT",
        "organization_name": "GTHT",
        "level_id": "root",
        "parent_username": "",
        "active": True,
    }


class _UnavailableControlStore:
    def load_accounts(self):
        raise ControlDatabaseUnavailable("control database is unavailable")

    def list_devices(self, **_kwargs):
        raise ControlDatabaseUnavailable("control database is unavailable")

    def load_organizations(self):
        raise ControlDatabaseUnavailable("control database is unavailable")

    def load_levels(self):
        raise ControlDatabaseUnavailable("control database is unavailable")

    def create_account(self, _account):
        raise ControlDatabaseUnavailable("control database is unavailable")


class _RecoveringControlStore:
    def __init__(self):
        self.accounts = []

    def load_accounts(self):
        return [dict(item) for item in self.accounts]

    def create_account(self, account):
        self.accounts.append(dict(account))

    def load_organizations(self):
        return [{"id": "default", "name": "Default", "description": ""}]

    def load_levels(self):
        return []


def _install_local_accounts(monkeypatch, tmp_path, accounts):
    import settings
    from tools.data.sqlite.account_manager.user import save_accounts

    monkeypatch.setattr(settings, "CACHE_DB_PATH", tmp_path / "unifieddata.sqlite")
    save_accounts(accounts)


def test_internal_manager_login_uses_existing_local_sqlite_when_postgres_is_down(
    tmp_path, monkeypatch,
):
    _install_local_accounts(monkeypatch, tmp_path, [_offline_account()])
    state = manager.ManagerState(tmp_path, "python")
    state.control_store = _UnavailableControlStore()

    token, principal, role = state.login("alice", "secret")

    assert token
    assert principal == "GTHT@alice@1"
    assert role == "user"


def test_internal_login_rejects_user_missing_from_local_sqlite(
    tmp_path, monkeypatch,
):
    _install_local_accounts(monkeypatch, tmp_path, [])
    state = manager.ManagerState(tmp_path, "python")
    state.control_store = _UnavailableControlStore()

    with pytest.raises(PermissionError):
        state.login("alice", "secret")


def test_http_login_rejects_missing_local_account_when_postgres_is_unavailable(
    tmp_path, monkeypatch,
):
    _install_local_accounts(monkeypatch, tmp_path, [])
    state = manager.ManagerState(tmp_path, "python")
    state.control_store = _UnavailableControlStore()

    with running_manager(state) as base_url:
        request = Request(
            f"{base_url}/auth/login",
            data=b'{"username":"alice","password":"secret"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as failed:
            urlopen(request)

    assert failed.value.code == 403
    payload = json.loads(failed.value.read().decode("utf-8"))
    assert payload["success"] is False


def test_offline_registration_is_local_and_queued_for_central_sync(
    tmp_path, monkeypatch,
):
    _install_local_accounts(monkeypatch, tmp_path, [])
    state = manager.ManagerState(tmp_path, "python")
    state.control_store = _UnavailableControlStore()

    principal, role, alias, organization_id = state.register("new_user", "secret")

    local = LocalAccountStore()
    assert principal.startswith("GTHT@new_user@")
    assert principal.rsplit("@", 1)[1].isdigit()
    assert role == "user"
    assert alias == "new_user"
    assert organization_id == "GTHT"
    assert local.load_accounts()[0]["username"] == principal
    assert local.pending_accounts()[0]["username"] == principal
    profiles = state.client_state.profiles(
        principal, include_local_paths=False,
    )
    assert profiles[0]["profile_id"] == "self"
    assert profiles[0]["profile_kind"] == "self"


def test_two_offline_managers_can_use_the_same_alias_without_username_collision(
    tmp_path, monkeypatch,
):
    _install_local_accounts(monkeypatch, tmp_path, [])
    state = manager.ManagerState(tmp_path, "python")
    state.control_store = _UnavailableControlStore()

    first, _role, _alias, _organization_id = state.register("same_alias", "secret")
    second, _role, _alias, _organization_id = state.register("same_alias", "secret")

    assert first != second
    assert len(LocalAccountStore().load_accounts()) == 2
    assert len(LocalAccountStore().pending_accounts()) == 2


def test_duplicate_alias_requires_full_username_for_offline_login(
    tmp_path, monkeypatch,
):
    _install_local_accounts(monkeypatch, tmp_path, [])
    state = manager.ManagerState(tmp_path, "python")
    state.control_store = _UnavailableControlStore()
    first, _role, _alias, _organization_id = state.register("same_alias", "secret")
    second, _role, _alias, _organization_id = state.register("same_alias", "secret")

    with pytest.raises(PermissionError):
        state.login("same_alias", "secret")
    _token, principal, _role = state.login(first, "secret")
    assert principal == first
    assert second != first


def test_pending_offline_registration_syncs_on_next_online_login(
    tmp_path, monkeypatch,
):
    _install_local_accounts(monkeypatch, tmp_path, [])
    state = manager.ManagerState(tmp_path, "python")
    state.control_store = _UnavailableControlStore()
    principal, _role, _alias, _organization_id = state.register(
        "new_user", "secret",
    )
    recovering = _RecoveringControlStore()
    state.control_store = recovering

    _token, authenticated_principal, _authenticated_role = state.login(
        "new_user", "secret",
    )

    assert authenticated_principal == principal
    assert recovering.accounts[0]["username"] == principal
    assert LocalAccountStore().pending_accounts() == []


def test_manager_scope_supports_alias_and_organization_alias_login(
    tmp_path, monkeypatch,
):
    gtht = _offline_account()
    gtht["username"] = "GTHT@MaxJJW@1"
    gtht["alias"] = "MaxJJW"
    default = {
        **gtht,
        "username": "default@MaxJJW@2",
        "organization_id": "default",
        "organization_name": "Default",
    }
    _install_local_accounts(monkeypatch, tmp_path, [gtht, default])
    state = manager.ManagerState(tmp_path, "python")
    state.control_store = _UnavailableControlStore()

    _token, principal, _role = state.login("MaxJJW", "secret")
    assert principal == "GTHT@MaxJJW@1"
    _token, principal, _role = state.login("GTHT@MaxJJW", "secret")
    assert principal == "GTHT@MaxJJW@1"
    with pytest.raises(PermissionError):
        state.login("default@MaxJJW", "secret")
    _token, principal, _role = state.login("default@MaxJJW@2", "secret")
    assert principal == "default@MaxJJW@2"


def test_alias_validation_is_case_sensitive_and_rejects_username_delimiters(
    tmp_path, monkeypatch,
):
    _install_local_accounts(monkeypatch, tmp_path, [])
    state = manager.ManagerState(tmp_path, "python")
    state.control_store = _UnavailableControlStore()

    first, _role, _alias, _org = state.register("MaxJJW", "secret")
    second, _role, _alias, _org = state.register("maxjjw", "secret")
    assert first != second
    with pytest.raises(ValueError, match=r"\$|@"):
        state.register("bad$name", "secret")
    with pytest.raises(ValueError, match=r"\$|@"):
        state.register("bad@name", "secret")


def test_registration_rejects_an_organization_outside_manager_scope(
    tmp_path, monkeypatch,
):
    _install_local_accounts(monkeypatch, tmp_path, [])
    state = manager.ManagerState(tmp_path, "python")
    state.control_store = _UnavailableControlStore()

    with pytest.raises(ValueError, match="不管理"):
        state.register("public_user", "secret", "default")


def test_profile_research_reads_manager_projection_without_business_port(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    calls = []
    monkeypatch.setattr(
        "server.manager.http.profile_research_routes."
        "ProfileResearchProjection.list_research",
        lambda _self, **values: calls.append(values) or {"items": []},
    )
    monkeypatch.setattr(
        state.gateway, "request",
        lambda **_values: pytest.fail("profile research must not use a business port"),
    )
    with running_manager(state) as base_url:
        request_value = Request(
            f"{base_url}/api/profile-research?lifecycle=active&limit=200",
            headers={"Authorization": "Bearer user-token"},
        )
        with urlopen(request_value) as response:
            value = json.loads(response.read())

    assert value["success"] is True
    assert calls == [{
        "owner": "user@1",
        "workspace_ref": "",
        "lifecycle": "active",
        "limit": 200,
        "after": "",
    }]


@pytest.mark.parametrize(
    ("path", "method_name"),
    (
        (
                "/api/factor-library/family-sources/public/MmClose2High/versions/current",
            "version",
        ),
        (
            (
                    "/api/factor-library/family-sources/custom/SubordinateFactor"
                "/versions/current?owner_username=GTHT%40child%401"
            ),
            "version",
        ),
        (
            (
                    "/api/factor-library/family-sources/custom/Momentum/versions"
                "?owner_username=GTHT%40child%401"
            ),
            "versions",
        ),
    ),
)
def test_factor_family_source_detail_uses_manager_catalog_without_gateway(
    tmp_path, monkeypatch, path: str, method_name: str,
) -> None:
    state = authenticated_state(tmp_path)
    calls = []

    class RejectGlobalApplicationLock:
        def __enter__(self):
            raise AssertionError("source object reads must not stall the application lock")

        def __exit__(self, *_args):
            return False

    def read(_catalog, principal, kind, factor_id, *args, **kwargs):
        calls.append((principal, kind, factor_id, args, kwargs))
        return {"success": True, "source_code": "available", "versions": []}

    monkeypatch.setattr(FactorSourceCatalog, method_name, read)
    state.application_request_lock = RejectGlobalApplicationLock()
    monkeypatch.setattr(
        state.gateway, "request",
        lambda **_values: pytest.fail("factor source must not use a business port"),
    )
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}{path}",
            headers={"Authorization": "Bearer user-token"},
        )) as response:
            value = json.loads(response.read())

    assert value["success"] is True
    assert calls[0][:3] in {
        ("user@1", "public", "MmClose2High"),
        ("user@1", "custom", "SubordinateFactor"),
        ("user@1", "custom", "Momentum"),
    }


@pytest.mark.parametrize(
    ("path", "expected_ref"),
    (
        (
            "/api/factor-library/family-sources/public/MmClose2High/versions/current",
            "public:MmClose2High",
        ),
        (
            (
                "/api/factor-library/family-sources/custom/SubordinateFactor"
                "/versions/current?owner_username=child%401"
            ),
            "child@1:SubordinateFactor",
        ),
    ),
)
def test_missing_factor_source_is_hydrated_once_before_detail_retry(
    tmp_path, monkeypatch, path: str, expected_ref: str,
) -> None:
    state = authenticated_state(tmp_path)
    calls = []
    hydrated = []

    def read(*_args, **_kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise FileNotFoundError("missing")
        return {"success": True, "source_code": "available"}

    def hydrate(_hydrator, factor_ref, *, principal):
        hydrated.append((factor_ref, principal))
        return True

    monkeypatch.setattr(FactorSourceCatalog, "version", read)
    monkeypatch.setattr(FactorSourceHydrator, "hydrate", hydrate)
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}{path}",
            headers={"Authorization": "Bearer user-token"},
        )) as response:
            value = json.loads(response.read())

    assert value["source_code"] == "available"
    assert hydrated == [(expected_ref, "user@1")]
    assert len(calls) == 2


def test_factor_source_detail_does_not_hydrate_an_unreadable_owner(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    def reject_source(*_args, **_kwargs):
        raise PermissionError("forbidden")

    def reject_hydration(*_args, **_values):
        raise AssertionError("an unreadable source must not be hydrated")

    monkeypatch.setattr(FactorSourceCatalog, "version", reject_source)
    monkeypatch.setattr(FactorSourceHydrator, "hydrate", reject_hydration)
    with running_manager(state) as base_url, pytest.raises(HTTPError) as raised:
        urlopen(Request(
            f"{base_url}/api/factor-library/family-sources/custom/Secret"
            "/versions/current?owner_username=unreadable%401",
            headers={"Authorization": "Bearer user-token"},
        ))

    assert raised.value.code == 403


def test_research_lifecycle_patch_uses_manager_database(tmp_path, monkeypatch) -> None:
    state = authenticated_state(tmp_path)
    calls = []
    monkeypatch.setattr(
        "server.manager.http.profile_research_routes.transition_lifecycle",
        lambda **values: calls.append(values) or {
            "lifecycle": "archived", "revision": 8,
        },
    )
    monkeypatch.setattr(
        state.gateway, "request",
        lambda **_values: pytest.fail("profile research must not use a business port"),
    )
    body = b'{"target":"archived","expected_revision":7}'
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/profile-research/work-package%3Aone/lifecycle?port=8141",
            data=body,
            method="PATCH",
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": "application/json",
            },
        )) as response:
            value = json.loads(response.read())

    assert value["lifecycle"] == "archived"
    assert response.headers["ETag"]
    assert calls == [{
        "owner": "user@1",
        "work_package_ref": "work-package:one",
        "target": "archived",
        "expected_revision": 7,
        "actor": "user@1",
        "reason": "",
    }]


def test_manager_session_can_resume_authorized_maintenance_on_selected_port(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(state, "preferred_service_port", lambda: 8141)
    monkeypatch.setattr(state, "service_ports", lambda: [8141])
    calls = []

    def request(**values):
        calls.append(values)
        return manager.GatewayResponse(
            status=200,
            body=b'{"success":true,"resume":{"packet_bytes":512}}',
            content_type="application/json",
        )

    monkeypatch.setattr(state.gateway, "request", request)
    body = b'{"role":"server_maintenance"}'
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/agent-flow/agents/root/resume?port=8141",
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": "application/json",
            },
        )) as response:
            value = json.loads(response.read())

    assert value["resume"]["packet_bytes"] == 512
    assert calls == [{
        "port": 8141,
        "path": "/api/agent-flow/agents/root/resume",
        "principal": "user@1",
        "method": "POST",
        "body": body,
        "content_type": "application/json",
    }]


def test_test_configuration_writes_are_manager_owned_without_service_port(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    calls = []

    class Authoring:
        @staticmethod
        def handles(path, method):
            return path == "/api/test-authoring/workspaces/workspace-one/configuration" and method == "PUT"

        @staticmethod
        def write(method, path, *, owner, payload):
            calls.append({
                "method": method, "path": path, "owner": owner,
                "payload": payload,
            })
            return _TestAuthoringResponse({
                "success": True,
                "configuration": {"revision": 2},
            })

    state.test_authoring = Authoring()
    monkeypatch.setattr(
        state.gateway, "request",
        lambda **_values: pytest.fail("authoring must not use a service gateway"),
    )
    monkeypatch.setattr(
        state, "service_ports",
        lambda: pytest.fail("authoring must not inspect service ports"),
    )
    body = b'{"expected_revision":1,"payload":{}}'
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/test-authoring/workspaces/workspace-one/configuration?port=8141",
            data=body,
            method="PUT",
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": "application/json",
            },
        )) as response:
            value = json.loads(response.read())

    assert value["configuration"]["revision"] == 2
    assert calls == [{
        "method": "PUT",
        "path": "/api/test-authoring/workspaces/workspace-one/configuration",
        "owner": "user@1",
        "payload": {"expected_revision": 1, "payload": {}},
    }]


def test_configuration_snapshot_is_manager_owned_without_service_port(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    calls = []
    service = TestAuthoringService()
    state.test_authoring = service

    def create_snapshot(**values):
        calls.append(values)
        return {
            "snapshot_id": "snapshot-one",
            "snapshot_revision": 1,
        }

    from server.services import research_configuration_snapshots
    monkeypatch.setattr(
        research_configuration_snapshots, "create_snapshot", create_snapshot,
    )
    monkeypatch.setattr(
        state.gateway, "request",
        lambda **_values: pytest.fail("snapshot must not use a service gateway"),
    )
    monkeypatch.setattr(
        state, "service_ports",
        lambda: pytest.fail("snapshot must not inspect service ports"),
    )
    body = json.dumps({
        "source_workspace_id": "workspace-one",
        "source_configuration_id": "configuration-one",
        "source_configuration_revision": 2,
        "name": "preview-one",
    }).encode()
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/test-authoring/workspaces/workspace-one/configuration-snapshots",
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": "application/json",
            },
        )) as response:
            value = json.loads(response.read())

    assert value["snapshot"] == {
        "snapshot_id": "snapshot-one",
        "snapshot_revision": 1,
    }
    assert calls == [{
        "owner": "user@1",
        "workspace_id": "workspace-one",
        "source_workspace_id": "workspace-one",
        "source_configuration_id": "configuration-one",
        "source_configuration_revision": 2,
        "name": "preview-one",
    }]


def test_workspace_draft_delete_is_manager_owned_without_service_port(
    monkeypatch,
) -> None:
    service = TestAuthoringService()
    calls = []
    from server.services import research_workspaces

    monkeypatch.setattr(
        research_workspaces,
        "delete_draft_workspace",
        lambda **values: calls.append(values) or {"deleted": True},
    )
    assert service.handles("/api/test-authoring/workspaces/workspace-one", "DELETE") is True
    assert service.handles("/api/workspaces/workspace-one", "DELETE") is False
    assert service.handles("/api/backtest/settings/ic_test", "GET") is False
    assert service.handles("/api/testers/modules", "GET") is False
    response = service.write(
        "DELETE", "/api/test-authoring/workspaces/workspace-one",
        owner="user@1", payload={},
    )

    assert response.payload == {
        "success": True, "deleted": True,
    }
    assert calls == [{"workspace_id": "workspace-one", "owner": "user@1"}]


def test_test_settings_are_available_without_execution_service(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state.gateway, "request",
        lambda **_values: pytest.fail("settings must not use a service gateway"),
    )
    monkeypatch.setattr(
        state, "service_ports",
        lambda: pytest.fail("settings must not inspect service ports"),
    )
    headers = {"Authorization": "Bearer user-token"}
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/test-authoring/modules/ic_test?port=8141",
            headers=headers,
        )) as response:
            settings = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/jobs/artifact-capabilities?port=8141",
            headers=headers,
        )) as response:
            outputs = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/product-library/data-source-categories?port=8141",
            headers=headers,
        )) as response:
            categories = json.loads(response.read())

    assert settings["success"] is True
    assert settings["application"] == "ic_test"
    assert settings["executable_modules"]
    assert settings["run_fields"][0]["key"] == "task_name"
    assert settings["run_fields"][0]["freeze_target"] == "job.task_name"
    assert outputs["outputs"]
    assert isinstance(categories["categories"], list)


def test_test_workbench_first_load_is_concurrent_and_service_port_free(
    tmp_path, monkeypatch,
) -> None:
    """The Manager must survive the real Promise.all first-page load.

    These endpoints import overlapping FactorTester packages.  Running them
    on separate request threads used to expose partially initialized modules
    or Python module-lock deadlocks on the first visit only.
    """
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state.gateway, "request",
        lambda **_values: pytest.fail("authoring must not use a service gateway"),
    )
    monkeypatch.setattr(
        state, "service_ports",
        lambda: pytest.fail("authoring must not inspect service ports"),
    )
    paths = (
        "/api/test-authoring/modules/ic_test",
        "/api/factor-library/families",
        "/api/factor-library/factors",
        "/api/product-library/product-groups",
        "/api/test-authoring/workspaces",
        "/api/test-authoring/configuration-templates",
        "/api/jobs/artifact-capabilities",
        "/api/product-library/data-source-categories",
        "/api/test-authoring/modules?parent=ic_test",
    )

    with running_manager(state) as base_url:
        def fetch(path: str) -> tuple[int, dict]:
            with urlopen(Request(
                f"{base_url}{path}",
                headers={"Authorization": "Bearer user-token"},
            ), timeout=15) as response:
                return response.status, json.loads(response.read())

        with ThreadPoolExecutor(max_workers=len(paths)) as pool:
            responses = list(pool.map(fetch, paths))

    assert [status for status, _payload in responses] == [200] * len(paths)
    assert all(payload.get("success") is not False for _status, payload in responses)


def test_legacy_product_group_creation_does_not_reach_business_port(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state.gateway,
        "request",
        lambda **_values: pytest.fail(
            "legacy product-group writes must not reach a business port"
        ),
    )
    body = b'{"name":"Group One","paths":["Products/Futures/CNFutures/_products/A.DCE"]}'
    with running_manager(state) as base_url:
        with pytest.raises(HTTPError) as exc_info:
            urlopen(Request(
                f"{base_url}/api/product-groups?port=8141",
                data=body,
                method="POST",
                headers={
                    "Authorization": "Bearer user-token",
                    "Content-Type": "application/json",
                },
            ))

    assert exc_info.value.code == 404


def test_run_submission_skips_route_without_data_capability(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state.test_authoring,
        "prepare_run_context",
        lambda payload, owner: {
            "schema_version": 1,
            "owner": owner,
            "run_spec_hash": "a" * 64,
            "prepared": {
                "workspace_id": payload["workspace_id"],
                "analyses": payload["analyses"],
            },
        },
    )
    routes = [
        manager.ServiceRoute(
            server_id="near-no-data", role="feat", branch="feat",
            revision="a", port=8141, latency_ms=1, online=True,
        ),
        manager.ServiceRoute(
            server_id="far-with-data", role="main", branch="main",
            revision="b", port=8000, latency_ms=5, online=True,
        ),
    ]
    monkeypatch.setattr(
        state, "service_routes", lambda include_offline=True: routes,
    )
    calls = []

    def route_request(route, **values):
        calls.append((route.server_id, values["path"]))
        if route.server_id == "near-no-data":
            return manager.GatewayResponse(
                status=422,
                body=(
                    b'{"success":false,"code":"data_capability_unavailable",'
                    b'"requirements":[{"product":"AG.SHF"}]}'
                ),
                content_type="application/json",
            )
        return manager.GatewayResponse(
            status=202,
            body=b'{"success":true,"run_id":"run-1"}',
            content_type="application/json",
        )

    monkeypatch.setattr(state, "route_request", route_request)
    body = b'{"workspace_id":"workspace-1","analyses":["backtest"]}'
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/runs",
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": "application/json",
            },
        )) as response:
            value = json.loads(response.read())

    assert value["success"] is True
    assert value["server_id"] == "far-with-data"
    assert value["execution_server_id"] == "far-with-data"
    assert response.headers["X-FactorTester-Service-Server"] == "far-with-data"
    assert calls == [
        ("near-no-data", "/api/runs/capability-preview"),
        ("far-with-data", "/api/runs/capability-preview"),
        ("far-with-data", "/api/runs"),
    ]


def test_run_submission_honours_the_requested_business_port(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state.test_authoring,
        "prepare_run_context",
        lambda payload, owner: {"owner": owner, "prepared": payload},
    )
    routes = [
        manager.ServiceRoute(
            server_id="feat-8141", role="feat", branch="feat",
            revision="a", port=8141, latency_ms=1, online=True,
        ),
        manager.ServiceRoute(
            server_id="main-8000", role="main", branch="main",
            revision="b", port=8000, latency_ms=2, online=True,
        ),
    ]
    monkeypatch.setattr(
        state, "service_routes", lambda include_offline=True: routes,
    )
    calls = []

    def route_request(route, **values):
        calls.append((route.server_id, route.port, values["path"]))
        return manager.GatewayResponse(
            status=(200 if values["path"].endswith("capability-preview") else 202),
            body=b'{"success":true,"run_id":"run-1"}',
            content_type="application/json",
        )

    monkeypatch.setattr(state, "route_request", route_request)
    body = b'{"workspace_id":"workspace-1","analyses":["backtest"]}'
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/runs?port=8000",
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": "application/json",
            },
        )) as response:
            value = json.loads(response.read())

    assert value["execution_server_id"] == "main-8000"
    assert value["execution_port"] == 8000
    assert calls == [
        ("main-8000", 8000, "/api/runs/capability-preview"),
        ("main-8000", 8000, "/api/runs"),
    ]


def test_remote_run_submission_uses_manager_frozen_authoring_context(
    tmp_path, monkeypatch,
) -> None:
    """A remote executor must not need the origin Manager's workspace DB."""
    state = authenticated_state(tmp_path)
    route = manager.ServiceRoute(
        server_id="remote-main", role="main", branch="main",
        revision="remote-revision", port=8000, latency_ms=5,
        online=True, remote=True,
        endpoint="http://10.77.0.1:7998",
        peer_control_endpoint="https://10.77.0.1:17998",
        proxy_token="peer-token",
    )
    monkeypatch.setattr(
        state, "service_routes", lambda include_offline=True: [route],
    )
    prepared_calls = []

    def prepare_run_context(payload, *, owner):
        prepared_calls.append((payload, owner))
        return {
            "schema_version": 1,
            "owner": owner,
            "run_spec_hash": "a" * 64,
            "prepared": {
                "workspace_id": payload["workspace_id"],
                "analyses": payload["analyses"],
            },
        }

    monkeypatch.setattr(
        state.test_authoring, "prepare_run_context", prepare_run_context,
        raising=False,
    )
    forwarded = []

    def route_request(selected, **values):
        payload = json.loads(values["body"])
        forwarded.append((values["path"], payload))
        context = payload.get("_manager_run_context")
        if not isinstance(context, dict):
            return manager.GatewayResponse(
                status=404,
                body=b'{"success":false,"error":"workspace configuration not found"}',
                content_type="application/json",
            )
        if values["path"] == "/api/runs/capability-preview":
            return manager.GatewayResponse(
                status=200,
                body=b'{"success":true,"capability":true}',
                content_type="application/json",
            )
        return manager.GatewayResponse(
            status=202,
            body=b'{"success":true,"run_id":"remote-run"}',
            content_type="application/json",
        )

    monkeypatch.setattr(state, "route_request", route_request)
    body = json.dumps({
        "workspace_id": "origin-workspace",
        "configuration_revision": 7,
        "analyses": ["ic"],
        # A client-provided reserved value must never reach the executor.
        "_manager_run_context": {"owner": "attacker"},
    }).encode()
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/runs?server_id=remote-main&port=8000",
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": "application/json",
            },
        )) as response:
            value = json.loads(response.read())

    assert response.status == 202
    assert value["run_id"] == "remote-run"
    assert prepared_calls == [({
        "workspace_id": "origin-workspace",
        "configuration_revision": 7,
        "analyses": ["ic"],
    }, "user@1")]
    assert [path for path, _payload in forwarded] == [
        "/api/runs/capability-preview", "/api/runs",
    ]
    assert all(
        payload["_manager_run_context"]["owner"] == "user@1"
        for _path, payload in forwarded
    )


def test_job_output_generation_uses_supplemental_route_and_forwards_body(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(state, "service_ports", lambda: [8141])
    calls = []

    def request(**values):
        calls.append(values)
        return manager.GatewayResponse(
            status=200,
            body=b'{"success":true,"artifacts":[]}',
            content_type="application/json",
        )

    monkeypatch.setattr(state.gateway, "request", request)
    body = b'{"kind":"report_output_generation","params":{"output_requests":["equity_curve"]}}'
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/jobs/job-one/supplementals?port=8141",
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": "application/json",
            },
        )) as response:
            value = json.loads(response.read())
        with pytest.raises(HTTPError) as rejected:
            urlopen(Request(
                f"{base_url}/api/jobs/job-one/artifacts/result?port=8141",
                data=body,
                method="POST",
                headers={
                    "Authorization": "Bearer user-token",
                    "Content-Type": "application/json",
                },
            ))

    assert value["success"] is True
    assert rejected.value.code == 404
    assert calls == [{
        "port": 8141,
        "path": "/api/jobs/job-one/supplementals",
        "principal": "user@1",
        "method": "POST",
        "body": body,
        "content_type": "application/json",
    }]


def test_job_supplementals_route_by_parent_storage_server_not_historical_port(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(
        tmp_path, "python", session_db_path=tmp_path / "manager.sqlite",
    )
    state._sessions[state._token_hash("user-token")] = (
        "user@1", "user", float("inf"),
    )
    monkeypatch.setattr(state, "service_ports", lambda: [8141])
    state.job_index.upsert("user@1", [{
        "job_id": "parent-one",
        "port": 8999,
        "storage_server_id": state.server_id,
        "updated_at": 10.0,
    }])
    calls = []

    def request(**values):
        calls.append(values)
        return manager.GatewayResponse(
            status=201,
            body=b'{"success":true,"created":true}',
            content_type="application/json",
        )

    monkeypatch.setattr(state.gateway, "request", request)
    body = b'{"kind":"backtest_strategy_analysis","params":{"analysis_tab":"returns"}}'
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/jobs/parent-one/supplementals?port=8999",
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": "application/json",
            },
        )) as response:
            value = json.loads(response.read())

    assert value["created"] is True
    assert calls == [{
        "port": 8141,
        "path": "/api/jobs/parent-one/supplementals",
        "principal": "user@1",
        "method": "POST",
        "body": body,
        "content_type": "application/json",
    }]


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    (
        ("GET", "/custom-analyses", None),
        ("POST", "/custom-analyses", b'{"title":"A","source":"result = 1"}'),
        ("PATCH", "/custom-analyses/tab-one", b'{"title":"B","source":"result = 2"}'),
        ("DELETE", "/custom-analyses/tab-one", None),
    ),
)
def test_job_custom_analysis_routes_use_parent_storage_server(
    tmp_path, monkeypatch, method: str, suffix: str, body: bytes | None,
) -> None:
    state = manager.ManagerState(
        tmp_path, "python", session_db_path=tmp_path / "manager.sqlite",
    )
    state._sessions[state._token_hash("user-token")] = (
        "user@1", "user", float("inf"),
    )
    monkeypatch.setattr(state, "service_ports", lambda: [8141])
    state.job_index.upsert("user@1", [{
        "job_id": "parent-one",
        "port": 8999,
        "storage_server_id": state.server_id,
        "updated_at": 10.0,
    }])
    calls = []

    def request(**values):
        calls.append(values)
        return manager.GatewayResponse(
            status=200,
            body=b'{"success":true,"analyses":[]}',
            content_type="application/json",
        )

    monkeypatch.setattr(state.gateway, "request", request)
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/jobs/parent-one{suffix}?port=8999",
            data=body,
            method=method,
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": "application/json",
            },
        )) as response:
            assert json.loads(response.read())["success"] is True

    expected = {
        "port": 8141,
        "path": f"/api/jobs/parent-one{suffix}",
        "principal": "user@1",
        "method": method,
    }
    if body is not None:
        expected.update({"body": body, "content_type": "application/json"})
    assert calls == [expected]


@pytest.mark.parametrize(
    ("path", "body"),
    (
        ("/api/jobs/job-one/approve", b"{}"),
        ("/api/jobs/job-one/cancel", b"{}"),
        ("/api/jobs/job-one/continue", b'{"action":"continue"}'),
        ("/api/jobs/job-one/retry", b"{}"),
    ),
)
def test_job_lifecycle_writes_use_selected_service_port(
    tmp_path, monkeypatch, path: str, body: bytes,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(state, "preferred_service_port", lambda: 8141)
    monkeypatch.setattr(state, "service_ports", lambda: [8141])
    calls = []

    def request(**values):
        calls.append(values)
        return manager.GatewayResponse(
            status=200,
            body=b'{"success":true,"job_id":"job-two"}',
            content_type="application/json",
        )

    monkeypatch.setattr(state.gateway, "request", request)
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}{path}?port=8141",
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": "application/json",
            },
        )) as response:
            value = json.loads(response.read())

    assert value["success"] is True
    assert calls == [{
        "port": 8141,
        "path": path,
        "principal": "user@1",
        "method": "POST",
        "body": body,
        "content_type": "application/json",
    }]


def test_run_workspace_clone_stays_in_manager(tmp_path, monkeypatch) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        "server.manager.http.research_object_routes.research_runs.load_run",
        lambda **_values: {
            "run_spec_hash": "a" * 64,
            "run_spec": {"configuration": {
                "schema_version": research_configurations.SCHEMA_VERSION,
            }},
        },
    )
    monkeypatch.setattr(
        "server.manager.http.research_object_routes."
        "research_workspaces.create_workspace",
        lambda **values: {"workspace_id": "workspace-one", **values},
    )
    monkeypatch.setattr(
        state.gateway, "request",
        lambda **_values: pytest.fail(
            "workspace clone must not use a business port",
        ),
    )
    with running_manager(state) as base_url, urlopen(Request(
        f"{base_url}/api/runs/run-one/clone-workspace?port=8141",
        data=b"{}",
        method="POST",
        headers={
            "Authorization": "Bearer user-token",
            "Content-Type": "application/json",
        },
    )) as response:
        value = json.loads(response.read())

    assert value["source_run_id"] == "run-one"
    assert value["workspace"]["owner"] == "user@1"


@pytest.mark.parametrize(
    ("path", "patch_target", "result_key"),
    (
        (
            "/api/trial-plans/direct/abc",
            "direct_trial_plan_registry.load",
            "trial_plan",
        ),
        (
            "/api/run-specs/abc",
            "research_runs.load_run_spec",
            "run_spec",
        ),
    ),
)
def test_research_objects_read_manager_database_without_business_port(
    tmp_path, monkeypatch, path: str, patch_target: str, result_key: str,
) -> None:
    state = authenticated_state(tmp_path)
    observed = []
    monkeypatch.setattr(
        f"server.manager.http.research_object_routes.{patch_target}",
        lambda **values: observed.append(values) or {"object": "available"},
    )
    monkeypatch.setattr(
        state.gateway, "request",
        lambda **_values: pytest.fail(
            "durable research objects must not use a business port",
        ),
    )
    with running_manager(state) as base_url, urlopen(Request(
        f"{base_url}{path}?port=8141",
        headers={"Authorization": "Bearer user-token"},
    )) as response:
        value = json.loads(response.read())

    assert value[result_key] == {"object": "available"}
    assert observed[0]["owner"] == "user@1"


def test_research_evidence_facets_read_manager_database(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        "server.manager.http.research_object_routes.list_facets",
        lambda **values: [{"owner": values["owner"]}],
    )
    monkeypatch.setattr(
        state.gateway, "request",
        lambda **_values: pytest.fail("Evidence must not use a business port"),
    )
    with running_manager(state) as base_url, urlopen(Request(
        f"{base_url}/api/research-evidence/facets?port=8141",
        headers={"Authorization": "Bearer user-token"},
    )) as response:
        value = json.loads(response.read())

    assert value["facets"] == [{"owner": "user@1"}]


def test_test_workbench_compiles_only_execution_settings_into_analysis() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "server" / "manager" / "web" / "workbench"
        / "test-configuration.js"
    ).read_text(encoding="utf-8")

    assert "FTTestConfigurationCompiler.executionSettings" in source
    assert "FTTestConfigurationCompiler.authoringSettings" in source
    assert "const settings = structuredClone(state.values);" not in source


def test_job_progress_stream_is_relayed_through_manager(tmp_path, monkeypatch) -> None:
    captured = {}

    class StreamHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            captured["path"] = self.path
            captured["principal"] = self.headers.get("X-FactorTester-Principal")
            captured["capability"] = self.headers.get("X-FactorTester-Manager")
            body = b"event: progress\ndata: {\"completed\":1}\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), StreamHandler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    port = upstream.server_address[1]
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(state, "service_ports", lambda: [port])
    try:
        with running_manager(state) as base_url:
            with urlopen(Request(
                f"{base_url}/api/jobs/job-one/stream?port={port}",
                headers={"Authorization": "Bearer user-token"},
            )) as response:
                body = response.read().decode("utf-8")
                routed_port = response.headers["X-FactorTester-Service-Port"]
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=2)

    assert routed_port == str(port)
    assert "event: progress" in body
    assert captured["path"] == "/api/jobs/job-one/stream"
    assert captured["principal"] == "user@1"
    assert captured["capability"] == state.capability_token()


def test_profiles_and_workspace_are_local_manager_projections(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    ensured = []
    monkeypatch.setattr(
        state.client_state, "ensure_self_profile", ensured.append,
    )
    monkeypatch.setattr(
        state.client_state, "profiles",
        lambda principal: [{"profile_id": "maxa", "principal": principal}],
    )
    monkeypatch.setattr(
        state.client_state, "workspace",
        lambda principal: {"principal_ref": principal, "schema_version": 1},
    )
    headers = {"Authorization": "Bearer user-token"}
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/client/profiles", headers=headers,
        )) as response:
            profiles = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/client/workspace", headers=headers,
        )) as response:
            workspace = json.loads(response.read())

    assert profiles["profiles"][0]["profile_id"] == "maxa"
    assert profiles["profiles"][0]["principal"] == "user@1"
    assert ensured == ["user@1"]
    assert workspace["workspace"]["principal_ref"] == "user@1"


def test_profile_projection_remains_available_when_postgres_is_offline(
    tmp_path,
) -> None:
    class OfflineControlStore:
        def list_profiles(self, _principal):
            raise ControlDatabaseUnavailable("postgresql is offline")

        def upsert_profile(self, *_args, **_kwargs):
            raise ControlDatabaseUnavailable("postgresql is offline")

    profile = {
        "profile_id": "maxa",
        "display_name": "Max A",
        "workspace_root": "/private/workspace",
        "session_ref": "private-session",
        "session_binding": {"principal_ref": "attacker"},
        "agents": [{"agent_id": "research-maxa", "role": "research"}],
    }
    service = ClientStateService(
        tmp_path / "client",
        control_store=OfflineControlStore(),
        profile_cache_root=tmp_path / "profile-cache",
    )

    receipt = service.sync_profile("user@1", profile)

    assert receipt["status"] == "pending"
    assert receipt["synced"] is False
    assert receipt["pending"] is True
    restored = ClientStateService(
        tmp_path / "different-client-root",
        control_store=OfflineControlStore(),
        profile_cache_root=tmp_path / "profile-cache",
    )
    profiles = restored.profiles("user@1", include_local_paths=False)
    assert profiles[0]["profile_id"] == "maxa"
    assert profiles[0]["session_binding"] == {"principal_ref": "user@1"}
    assert "workspace_root" not in profiles[0]
    assert "session_ref" not in profiles[0]


def test_ensure_self_profile_creates_metadata_without_a_workspace(tmp_path) -> None:
    client_root = tmp_path / "client"
    service = ClientStateService(
        client_root,
        control_store=None,
        profile_cache_root=tmp_path / "profile-cache",
    )

    receipt = service.ensure_self_profile("user@1")

    assert receipt["status"] == "pending"
    assert receipt["profile"]["profile_id"] == "self"
    assert receipt["profile"]["profile_kind"] == "self"
    assert receipt["profile"]["session_binding"] == {
        "principal_ref": "user@1",
    }
    assert service.profile_cache.read("user@1") == [receipt["profile"]]
    assert not client_root.exists()


def test_ensure_self_profile_repairs_kind_without_losing_profile_content(
    tmp_path,
) -> None:
    from server.manager.services.profile_projection import ProfileProjectionCache

    cache = ProfileProjectionCache(tmp_path / "profile-cache")
    cache.upsert("user@1", {
        "schema_version": 9,
        "profile_id": "self",
        "display_name": "legacy",
        "agents": [{"agent_id": "research-agent"}],
        "research_records": [{"record_id": "report-one"}],
        "session_binding": {"principal_ref": "user@1"},
    })
    service = ClientStateService(
        tmp_path / "client",
        control_store=None,
        profile_cache_root=tmp_path / "profile-cache",
    )

    receipt = service.ensure_self_profile("user@1")

    assert receipt["profile"]["profile_kind"] == "self"
    assert receipt["profile"]["display_name"] == "self"
    assert receipt["profile"]["agents"] == [{"agent_id": "research-agent"}]
    assert receipt["profile"]["research_records"] == [
        {"record_id": "report-one"},
    ]


def test_profile_projection_flushes_after_postgres_recovers(tmp_path) -> None:
    class RecoveringControlStore:
        def __init__(self):
            self.online = False
            self.rows = []

        def list_profiles(self, _principal):
            if not self.online:
                raise ControlDatabaseUnavailable("postgresql is offline")
            return list(self.rows)

        def upsert_profile(self, principal, profile_id, display_name, payload):
            if not self.online:
                raise ControlDatabaseUnavailable("postgresql is offline")
            self.rows.append({
                "principal": principal,
                "profile_id": profile_id,
                "display_name": display_name,
                "payload": payload,
            })

    control = RecoveringControlStore()
    service = ClientStateService(
        tmp_path / "client",
        control_store=control,
        profile_cache_root=tmp_path / "profile-cache",
    )
    service.sync_profile("user@1", {
        "profile_id": "maxa",
        "display_name": "Max A",
        "agents": [{"agent_id": "research-maxa"}],
    })
    assert control.rows == []

    control.online = True
    profiles = service.profiles("user@1", include_local_paths=False)

    assert [item["profile_id"] for item in profiles] == ["maxa"]
    assert [item["profile_id"] for item in control.rows] == ["maxa"]
    assert "workspace_root" not in control.rows[0]["payload"]
    assert control.rows[0]["payload"]["session_binding"] == {
        "principal_ref": "user@1",
    }


def test_profile_sync_endpoint_reports_local_pending_state_on_postgres_outage(
    tmp_path,
) -> None:
    state = authenticated_state(tmp_path)

    class OfflineControlStore:
        def upsert_profile(self, *_args, **_kwargs):
            raise ControlDatabaseUnavailable("postgresql is offline")

        def list_profiles(self, _principal):
            raise ControlDatabaseUnavailable("postgresql is offline")

    state.client_state.control_store = OfflineControlStore()
    headers = {
        "Authorization": "Bearer user-token",
        "Content-Type": "application/json",
    }
    body = json.dumps({
        "profile": {
            "profile_id": "maxa",
            "display_name": "Max A",
            "workspace_root": "/private/workspace",
        },
    }).encode()

    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/client/profiles/sync",
            data=body,
            method="POST",
            headers=headers,
        )) as response:
            value = json.loads(response.read())

    assert response.status == 200
    assert value["success"] is True
    assert value["status"] == "pending"
    assert value["synced"] is False
    assert value["reason"] == "control database is unavailable"
    assert value["profile"]["session_binding"] == {"principal_ref": "user@1"}
    assert "workspace_root" not in value["profile"]


def test_profile_create_endpoint_registers_minimal_server_projection(
    tmp_path,
) -> None:
    from server.manager.services.profile_projection import ProfileProjectionCache

    state = authenticated_state(tmp_path)
    state.client_state.control_store = None
    state.client_state.client_root = tmp_path / "client"
    state.client_state.profile_cache = ProfileProjectionCache(
        tmp_path / "profile-cache",
    )
    state.client_state.account_domain_sync = None
    state.federated_public_data = None
    headers = {
        "Authorization": "Bearer user-token",
        "Content-Type": "application/json",
    }

    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/client/profiles/create",
            data=json.dumps({
                "profile_id": "maxc",
                "display_name": "MaxC",
            }).encode(),
            method="POST",
            headers=headers,
        )) as response:
            created_status = response.status
            created = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/client/profiles",
            headers={"Authorization": "Bearer user-token"},
        )) as response:
            listed = json.loads(response.read())

    assert created_status == 201
    assert created["success"] is True
    assert created["status"] == "pending"
    assert created["profile"]["profile_id"] == "maxc"
    assert created["profile"]["display_name"] == "MaxC"
    assert created["profile"]["runtime_kind"] == "server"
    assert "workspace_root" not in created["profile"]
    assert listed["profiles"][0]["profile_id"] == "maxc"


def test_profile_create_endpoint_rejects_duplicate_identifier(tmp_path) -> None:
    from server.manager.services.profile_projection import ProfileProjectionCache

    state = authenticated_state(tmp_path)
    state.client_state.control_store = None
    state.client_state.client_root = tmp_path / "client"
    state.client_state.profile_cache = ProfileProjectionCache(
        tmp_path / "profile-cache",
    )
    state.client_state.account_domain_sync = None
    state.federated_public_data = None
    state.client_state.create_profile(
        "user@1", profile_id="maxc", display_name="MaxC",
    )
    headers = {
        "Authorization": "Bearer user-token",
        "Content-Type": "application/json",
    }

    with running_manager(state) as base_url:
        with pytest.raises(HTTPError) as raised:
            urlopen(Request(
                f"{base_url}/api/client/profiles/create",
                data=json.dumps({
                    "profile_id": "maxc",
                    "display_name": "Another MaxC",
                }).encode(),
                method="POST",
                headers=headers,
            ))

    assert raised.value.code == 409
    value = json.loads(raised.value.read())
    assert "profile already exists" in value["error"]


def test_profile_create_rejects_reserved_self_identifier(tmp_path) -> None:
    service = ClientStateService(tmp_path / "client", control_store=None)

    with pytest.raises(ValueError, match="reserved"):
        service.create_profile(
            "user@1", profile_id="self", display_name="Pretend Self",
        )


def test_profile_sync_rejects_reserved_self_identifier(tmp_path) -> None:
    service = ClientStateService(tmp_path / "client", control_store=None)

    with pytest.raises(ValueError, match="reserved"):
        service.sync_profile("user@1", {
            "profile_id": "self",
            "display_name": "Pretend Self",
        })


def test_language_preference_is_scoped_to_the_authenticated_user(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    headers = {
        "Authorization": "Bearer user-token",
        "Content-Type": "application/json",
    }
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/client/preferences",
            data=b'{"language":"en"}',
            headers=headers,
            method="POST",
        )) as response:
            updated = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/client/preferences",
            headers={"Authorization": "Bearer user-token"},
        )) as response:
            restored = json.loads(response.read())

    assert updated["preferences"]["language"] == "en"
    assert updated["preferences"]["configured"] is True
    assert restored["preferences"]["language"] == "en"
    assert restored["preferences"]["configured"] is True
    assert state.user_preferences.read("other-user")["language"] == "system"
    assert state.user_preferences.read("other-user")["configured"] is False


def test_language_preference_uses_postgres_once_then_local_cache(tmp_path) -> None:
    class ControlStore:
        def __init__(self):
            self.loads = []
            self.updates = []

        def load_user_preference(self, principal):
            self.loads.append(principal)
            return {"language": "en", "updated_at": "2026-08-13T12:00:00Z"}

        def upsert_user_preference(self, principal, *, language):
            self.updates.append((principal, language))
            return {"language": language, "updated_at": "2026-08-13T12:01:00Z"}

    control = ControlStore()
    preferences = UserPreferenceStore(
        tmp_path / "preferences",
        control_store=control,
        cache_ttl_seconds=300,
    )

    assert preferences.read("alice")["language"] == "en"
    assert preferences.read("alice")["configured"] is True
    assert preferences.read("alice")["language"] == "en"
    assert control.loads == ["alice"]

    assert preferences.update("alice", {"language": "zh-Hans"})["language"] == "zh-Hans"
    assert control.updates == [("alice", "zh-Hans")]


def test_language_preference_migrates_legacy_local_value_once(tmp_path) -> None:
    class ControlStore:
        def __init__(self):
            self.loads = []
            self.updates = []

        def load_user_preference(self, principal):
            self.loads.append(principal)
            return None

        def upsert_user_preference(self, principal, *, language):
            self.updates.append((principal, language))
            return {"language": language}

    root = tmp_path / "preferences"
    local = UserPreferenceStore(root)
    local._atomic_write(local._path("alice"), {
        "schema_version": 1,
        "language": "en",
    })
    control = ControlStore()
    shared = UserPreferenceStore(root, control_store=control)

    assert shared.read("alice")["language"] == "en"
    assert shared.read("alice")["configured"] is True
    assert shared.read("alice")["language"] == "en"
    assert control.loads == ["alice"]
    assert control.updates == [("alice", "en")]


def test_language_preference_caches_missing_postgres_default(tmp_path) -> None:
    class ControlStore:
        def __init__(self):
            self.loads = []

        def load_user_preference(self, principal):
            self.loads.append(principal)
            return None

    control = ControlStore()
    preferences = UserPreferenceStore(
        tmp_path / "preferences", control_store=control,
    )

    first = preferences.read("alice")
    restored = preferences.read("alice")

    assert first == {
        "schema_version": 1,
        "language": "system",
        "configured": False,
    }
    assert restored == first
    assert control.loads == ["alice"]


def test_cached_default_is_not_migrated_as_explicit_system(tmp_path) -> None:
    class ControlStore:
        def __init__(self):
            self.loads = []
            self.updates = []

        def load_user_preference(self, principal):
            self.loads.append(principal)
            return None

        def upsert_user_preference(self, principal, *, language):
            self.updates.append((principal, language))
            return {"language": language}

    control = ControlStore()
    preferences = UserPreferenceStore(
        tmp_path / "preferences", control_store=control,
    )
    assert preferences.read("alice")["configured"] is False
    cached = preferences._read_local("alice")
    cached["cached_at"] = 0
    preferences._atomic_write(preferences._path("alice"), cached)

    assert preferences.read("alice")["configured"] is False
    assert control.loads == ["alice", "alice"]
    assert control.updates == []


def test_legacy_cached_default_is_refreshed_without_becoming_explicit(
    tmp_path,
) -> None:
    class ControlStore:
        def __init__(self):
            self.loads = []
            self.updates = []

        def load_user_preference(self, principal):
            self.loads.append(principal)
            return None

        def upsert_user_preference(self, principal, *, language):
            self.updates.append((principal, language))
            return {"language": language}

    control = ControlStore()
    preferences = UserPreferenceStore(
        tmp_path / "preferences", control_store=control,
    )
    preferences._atomic_write(preferences._path("alice"), {
        "schema_version": 1,
        "language": "system",
        "cached_at": 10**20,
    })

    assert preferences.read("alice")["configured"] is False
    assert control.loads == ["alice"]
    assert control.updates == []


def test_language_preference_write_reports_control_database_outage(tmp_path) -> None:
    state = authenticated_state(tmp_path)

    def unavailable(_principal, _payload):
        raise ControlDatabaseUnavailable("control database is unavailable")

    state.user_preferences.update = unavailable
    with running_manager(state) as base_url:
        request = Request(
            f"{base_url}/api/client/preferences",
            data=b'{"language":"en"}',
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with pytest.raises(HTTPError) as failed:
            urlopen(request)

    assert failed.value.code == 503
    assert "temporarily unavailable" in failed.value.read().decode()


def test_web_language_precedence_keeps_explicit_and_cached_user_preferences() -> None:
    i18n = ROOT / "server" / "manager" / "web" / "core" / "i18n.js"
    program = f"""
global.window = globalThis;
const values = new Map();
global.localStorage = {{
  getItem: key => values.get(key) || null,
  setItem: (key, value) => values.set(key, value),
}};
eval(require("fs").readFileSync({json.dumps(str(i18n))}, "utf8"));
FTI18n.rememberPreference("zh-Hans");
console.log(JSON.stringify([
  FTI18n.choosePreference("zh-Hans", "en", "en"),
  FTI18n.choosePreference("", "zh-Hans", "en"),
  FTI18n.choosePreference("", "", FTI18n.storedPreference()),
]));
"""
    result = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True, text=True,
    )
    assert json.loads(result.stdout) == ["zh-Hans", "zh-Hans", "zh-Hans"]

    shell = (ROOT / "server" / "manager" / "web" / "app" / "shell.js").read_text()
    assert "FTI18n.choosePreference(" in shell
    assert "FTI18n.rememberPreference(preference)" in shell
    assert "state.session?.alias || state.session?.username" in shell


def test_local_catalog_capability_requires_the_native_swift_bridge() -> None:
    runtime = ROOT / "server" / "manager" / "web" / "app" / "runtime.js"
    program = f"""
global.window = globalThis;
eval(require("fs").readFileSync({json.dumps(str(runtime))}, "utf8"));
const browser = FTAppRuntime.hasLocalCatalog();
global.webkit = {{messageHandlers: {{factorTesterLocalCatalog: {{
  postMessage: () => ({{}}),
}}}}}};
const swift = FTAppRuntime.hasLocalCatalog();
console.log(JSON.stringify({{browser, swift}}));
"""
    result = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True, text=True,
    )

    assert json.loads(result.stdout) == {"browser": False, "swift": True}


def test_web_runtime_retries_read_only_requests_after_transient_disconnect() -> None:
    runtime = ROOT / "server" / "manager" / "web" / "app" / "runtime.js"
    program = f"""
global.window = globalThis;
global.document = {{querySelector: () => ({{}})}};
global.localStorage = {{getItem: () => null}};
global.sessionStorage = {{getItem: () => null}};
eval(require("fs").readFileSync({json.dumps(str(runtime))}, "utf8"));
let attempts = 0;
global.fetch = async (_path, options) => {{
  attempts += 1;
  if (attempts < 3) throw new TypeError("Load failed");
  return {{status: 200, ok: true, json: async () => ({{success: true}})}};
}};
(async () => {{
  const value = await FTAppRuntime.create().api("/api/factor-library/factors");
  console.log(JSON.stringify({{value, attempts}}));
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""
    result = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True, text=True,
    )
    assert json.loads(result.stdout) == {
        "value": {"success": True},
        "attempts": 3,
    }


def test_web_runtime_does_not_retry_mutating_requests_after_disconnect() -> None:
    runtime = ROOT / "server" / "manager" / "web" / "app" / "runtime.js"
    program = f"""
global.window = globalThis;
global.document = {{querySelector: () => ({{}})}};
global.localStorage = {{getItem: () => null}};
global.sessionStorage = {{getItem: () => null}};
eval(require("fs").readFileSync({json.dumps(str(runtime))}, "utf8"));
let attempts = 0;
global.fetch = async (_path, _options) => {{
  attempts += 1;
  throw new TypeError("Load failed");
}};
(async () => {{
  try {{
    await FTAppRuntime.create().api("/api/product-library/categories", {{method: "POST"}});
  }} catch (_) {{}}
  console.log(JSON.stringify({{attempts}}));
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""
    result = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True, text=True,
    )
    assert json.loads(result.stdout) == {"attempts": 1}


def test_web_localization_is_projected_from_the_apple_catalog(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/api/localizations/en") as response:
            english = json.loads(response.read())
        with urlopen(f"{base_url}/api/localizations/zh-Hans") as response:
            chinese = json.loads(response.read())

    assert english["locale"] == "en"
    assert chinese["locale"] == "zh-Hans"
    assert english["strings"]["本地研究"] == "Local research"
    assert english["strings"]["需要登录"] == "Sign in required"
    assert english["strings"]["登录后才能查看或撤销自己的设备"] == (
        "Sign in to view or revoke your devices"
    )
    assert english["strings"]["我的设备"] == "My devices"
    assert english["strings"]["仅公网访客模式"] == "Public visitor mode only"
    assert english["strings"]["研究身份"] == "Profile"
    assert english["strings"]["研究身份：%@"] == "Profile: %@"
    assert english["strings"]["Profiles"] == "Profile"
    assert chinese["strings"]["研究身份"] == "研究身份"
    assert chinese["strings"]["Profile"] == "研究身份"
    assert chinese["strings"]["Profiles"] == "研究身份"
    assert chinese["strings"]["请使用 CLI 注册研究 Agent Profile"] == (
        "请使用 CLI 注册智能体研究身份"
    )
    assert english["strings"]["请使用 CLI 注册研究 Agent Profile"] == (
        "Use the CLI to register an Agent Profile"
    )
    assert "Research Identities" not in english["strings"].values()

    profile_page = (
        ROOT / "server" / "manager" / "web" / "profile" / "profiles.js"
    ).read_text(encoding="utf-8")
    assert 'context.setHeading(context.t("研究身份")' in profile_page
    assert 'FTUI.table([context.t("研究身份")' in profile_page


def test_every_client_page_and_detail_route_uses_the_unified_shell(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    paths = [
        "/", "/research", "/research/report-publication",
        "/jobs", "/jobs/8141/job-one", "/factors",
        "/factors/families", "/factors/factor/factor-one",
        "/factors/family/family-one", "/factors/set/set-one",
        "/products", "/products/groups", "/products/product/SI.GFE",
        "/products/group/day", "/profiles", "/profiles/maxa",
        "/ic-test", "/backtest", "/test-templates/template-one",
        "/settings", "/settings/workspace", "/manager",
    ]
    with running_manager(state) as base_url:
        for path in paths:
            with urlopen(f"{base_url}{path}") as response:
                body = response.read().decode("utf-8")
            assert response.status == 200
            assert "<title>FTClient</title>" in body


def test_web_shell_allows_authenticated_blob_image_previews(tmp_path) -> None:
    """Artifact previews use object URLs after the authenticated fetch."""
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(base_url) as response:
            assert response.headers["Content-Security-Policy"] == (
                "default-src 'self'; img-src 'self' blob: data: https:; "
                "style-src 'self' 'unsafe-inline'; "
                "script-src 'self' https://cdn.platform.openai.com; "
                "frame-src 'self' https://cdn.platform.openai.com; "
                "connect-src 'self' http: https:"
            )
            assert response.headers["Cache-Control"] == "no-store"


def test_web_shell_exposes_public_asset_revision(tmp_path) -> None:
    state = manager.ManagerState(tmp_path, "python")
    with running_manager(state) as base_url:
        with urlopen(base_url) as response:
            shell = response.read().decode("utf-8")
        with urlopen(f"{base_url}/api/client-assets/revision") as response:
            value = json.loads(response.read())
            assert response.headers["Cache-Control"] == "no-store"

    revision = value["revision"]
    assert value["success"] is True
    assert len(revision) == 64
    assert f'name="ft-client-assets-revision" content="{revision}"' in shell
    assert f"?v={revision}" in shell


def test_versioned_web_code_is_cached_but_shell_and_manifest_revalidate(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(base_url) as response:
            assert response.headers["Cache-Control"] == "no-store"
        with urlopen(f"{base_url}/research-static/module-manifest.json") as response:
            assert response.headers["Cache-Control"] == "no-store"
        with urlopen(f"{base_url}/research-static/core/icons.js?v=revision") as response:
            assert response.headers["Cache-Control"] == (
                "public, max-age=31536000, immutable"
            )


def test_unified_shell_loads_shared_test_workbench_components(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(base_url) as response:
            shell = response.read().decode("utf-8")
        scripts = {}
        manifest = json.loads((research_static.WEB_ROOT / "module-manifest.json").read_text())
        initial_scripts = set(
            research_static._initial_scripts(manifest)
            + manifest.get("initial_external_scripts", [])
        )
        for relative in (
                "workbench/test-settings.js", "workbench/test-setting-fields.js",
                "workbench/test-factors.js",
                "workbench/test-factor-candidates.js",
                "workbench/test-factor-candidate-sources.js",
                "catalog/factor-editor.js",
                "workbench/factor-family-picker.js",
            "workbench/test-configuration-compiler.js",
            "workbench/test-object-picker.js",
            "workbench/test-object-editor-overlay.js",
            "workbench/test-products.js",
            "workbench/test-categories.js",
            "workbench/backtest-group-model.js",
            "workbench/backtest-group-form.js",
            "workbench/backtest-groups.js",
            "workbench/test-configuration.js",
            "workbench/tab-chip-content.js",
            "workbench/tab-list-chip.js",
            "workbench/test-templates.js", "workbench/test-content-adapters.js",
            "workbench/templates/actions.js",
            "workbench/test-run-results.js",
            "workbench/test-run-progress.js",
            "workbench/run-batch/model.js",
            "workbench/test-run-batch.js",
            "workbench/run-batch/actions.js",
            "workbench/tests.js",
        ):
            with urlopen(f"{base_url}/research-static/{relative}") as response:
                key = (
                    "run-batch-actions.js"
                    if relative == "workbench/run-batch/actions.js"
                    else relative.rsplit("/", 1)[-1]
                )
                scripts[key] = response.read().decode("utf-8")
            if relative in initial_scripts:
                assert f'/research-static/{relative}' in shell
            else:
                assert f'/research-static/{relative}' not in shell

    assert "/api/test-authoring/modules/" in scripts["tests.js"]
    assert "servicePath(`/api/test-authoring/modules/" not in scripts["tests.js"]
    assert "/api/test-authoring/workspaces" in scripts["tests.js"]
    assert 'servicePath("/api/test-authoring/workspaces")' not in scripts["tests.js"]
    assert "/api/runs/preview" in scripts["run-batch-actions.js"]
    assert "ensureFactorsForExecution" in scripts["run-batch-actions.js"]
    assert "ensureProductsForExecution" in scripts["run-batch-actions.js"]
    assert "workbench-run-submit" in scripts["tests.js"]
    assert 'analyses: [state.kind]' in scripts["run-batch-actions.js"]
    assert "/api/runs" in scripts["run-batch-actions.js"]
    assert 'serviceRunPath(context, state, "/api/runs/preview")' in scripts["run-batch-actions.js"]
    assert 'serviceRunPath(context, state, "/api/runs")' in scripts["run-batch-actions.js"]
    assert "FTICResults?.section" in scripts["test-run-results.js"]
    assert "FTBacktestResults?.section" in scripts["test-run-results.js"]
    assert "window.FTJobs.loadDetail" in scripts["test-run-results.js"]
    assert "local-settings" in scripts["test-settings.js"]
    assert "FTTabChipContent.create" in scripts["test-settings.js"]
    assert "FTTestContentAdapters.render" in scripts["test-settings.js"]
    assert "externalTabs" not in scripts["test-settings.js"]
    factor_candidates = scripts["test-factor-candidates.js"]
    assert 'selectField(context.t("因子家族")' not in scripts["test-factors.js"]
    assert 'selectField(context.t("因子")' not in scripts["test-factors.js"]
    assert "window.FTFactorFamilyPicker" in scripts["factor-family-picker.js"]
    assert "restoreFrozenSelections(state)" in scripts["test-factors.js"]
    assert "window.FTTestFactorCandidates" in factor_candidates
    assert "selectedProjections" in scripts["test-products.js"]
    assert "FTTestObjectEditorOverlay.open" in scripts["test-products.js"]
    assert "FTTestObjectPicker.create" in scripts["test-products.js"]
    assert "FTTestObjectPicker" in scripts["test-object-picker.js"]
    assert "FTTestObjectEditorOverlay" in scripts["test-object-editor-overlay.js"]
    assert "/api/product-library/data-source-categories" in scripts["test-categories.js"]
    assert "window.FTTestConfiguration" in scripts["test-configuration.js"]
    assert "window.FTTestConfigurationCompiler" in scripts[
        "test-configuration-compiler.js"
    ]
    assert "window.FTBacktestGroupModel" in scripts["backtest-group-model.js"]
    assert "window.FTBacktestGroupForm" in scripts["backtest-group-form.js"]
    assert "window.FTBacktestGroups" in scripts["backtest-groups.js"]
    assert "FTConfigurationGroupSurface.flows(state, surfaceKey)" in scripts[
        "backtest-groups.js"
    ]
    assert "FTConfigurationGroupSurface.render" in scripts["backtest-groups.js"]
    assert 'className: "backtest-groups"' in scripts["backtest-groups.js"]
    assert "FTConfigurationGroupSurface.surfaces(state)" in scripts[
        "backtest-groups.js"
    ]
    assert "surface?.content_adapter" in scripts["backtest-groups.js"]
    assert "implementedFlows" not in scripts["backtest-groups.js"]
    assert "FTConfigurationGroupSurface?.renderer?.(state.kind)" in scripts[
        "tests.js"
    ]
    assert "groupRenderer?.render" in scripts["tests.js"]
    assert "FTTestContentAdapters.chipSources(state)" in scripts["tests.js"]
    assert "externalTabs" not in scripts["tests.js"]
    assert "selectionPanel" not in scripts["tests.js"]
    assert "factor_owner_ref" not in scripts["test-factors.js"]
    assert "factor_git_commit" not in scripts["test-factors.js"]
    assert "factor_family_ref" not in scripts["test-factors.js"]
    assert "factor_params" not in scripts["test-factors.js"]
    assert "window.FTTestFactorCandidateSources" in scripts[
        "test-factor-candidate-sources.js"
    ]
    assert "FTFactors.factorDetail" in scripts[
        "test-object-editor-overlay.js"
    ]
    assert "function parameterEditor" in scripts["factor-editor.js"]
    assert "setting_template" not in scripts["tests.js"]
    assert 'test_templates: Object.freeze' in scripts["test-content-adapters.js"]
    assert "FTTestTemplates.panel" in scripts["test-content-adapters.js"]
    assert "window.FTTabChipContent" in scripts["tab-chip-content.js"]
    assert "window.FTTabListChip" in scripts["tab-list-chip.js"]
    assert "/test-templates/" in scripts["test-templates.js"]
    assert "handlers.overwrite(item)" in scripts["test-templates.js"]
    assert "handlers.delete(item)" in scripts["test-templates.js"]
    assert 'actions.className = "row-actions template-icon-actions"' in scripts[
        "test-templates.js"
    ]
    assert 'iconAction(context, "加载", "arrow.down.circle"' in scripts[
        "test-templates.js"
    ]
    assert 'iconAction(context, "覆盖", "square.and.pencil"' in scripts[
        "test-templates.js"
    ]
    assert 'iconAction(context, "删除", "trash"' in scripts["test-templates.js"]
    assert 'method: "PUT"' in scripts["actions.js"]
    assert 'method: "DELETE"' in scripts["actions.js"]


def test_web_shell_has_swift_style_opened_tabs_and_per_tab_test_state(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(base_url) as response:
            shell = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/coordinator.js") as response:
            research = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/runtime.js") as response:
            runtime = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/shell.js") as response:
            shell_module = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/report-entry.js") as response:
            report_entry = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/source.js") as response:
            report_source = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/rich-text.js") as response:
            rich_text = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/tabs.js") as response:
            tabs = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/tab-view-cache.js") as response:
            tab_view_cache = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/workbench/tests.js") as response:
            tests = response.read().decode("utf-8")

    assert 'id="opened-tabs"' in shell
    assert 'id="opened-caption"' in shell
    assert "function closeTab" in tabs
    assert "function renderOpenedTabs" in tabs
    assert "forceNew: true" in tabs
    assert "activeTabHasOverlay" in tabs
    assert "markActiveViewReady" in research
    assert "sessionStorage" in tab_view_cache
    assert "activeTabHasOverlay" in tab_view_cache
    assert "viewReady" in tab_view_cache
    assert "window.FTAppRuntime" in runtime
    assert "Object.freeze" in runtime
    assert "FTAppRuntime.create()" in research
    assert "window.FTAppShell" in shell_module
    assert "FTAppShell.create({state, api, t, tabs})" in research
    assert "activeRouteToken" in research
    assert "isRouteCurrent" in research
    assert "const isCurrent = () => context.isRouteCurrent?.() !== false;" in report_entry
    assert "error?.status !== 404" in report_source
    assert "FTReportSource.create" in report_entry
    assert "error.status = response.status" in runtime
    assert "messageHandlers?.researchReference" in report_entry
    assert "nativeReference" in report_entry
    assert "labelOverride" in report_entry
    assert "component_id" in report_entry
    assert "detail_fields" in report_entry
    assert "jobPrefix" in report_entry
    assert 'type === "profile"' in report_entry
    assert "context.nativeReference" in rich_text
    assert "context?.openReference?.(target, label)" in rich_text
    assert 'path.startsWith("/jobs/")' in tabs
    assert "function researchReportTabID(path)" in tabs
    assert "research-report:${encodeURIComponent(target)}" in tabs
    assert "tabID: state.activeTabID" in research
    assert "session.durable.heading = {" in report_entry
    assert "function invalidateLegacyReportView(tabID, session)" in tab_view_cache
    assert "context.tabID || `report:${publicationID}`" in report_entry
    assert r"const reportMatch = /^\/research\/(.+)$/" in tab_view_cache
    assert "decodeURIComponent(publicationID)" in tab_view_cache
    assert "context.tabSession" in tests


def test_swift_research_shell_keeps_section_switches_in_the_pinned_tab() -> None:
    source = (
        ROOT / "apple" / "Sources" / "Navigation" / "ClientTabView.swift"
    ).read_text(encoding="utf-8")
    block_start = source.index("case .research:")
    block_end = source.index("case .jobs:", block_start)
    block = source[block_start:block_end]
    assert "openResearchPath: openEmbeddedNavigation" in block
    assert "open(.researchReport(path:" not in block


def test_web_opened_tab_icons_are_separate_from_labels_and_jobs_have_status_time_presentation() -> None:
    tabs = (ROOT / "server" / "manager" / "web" / "app" / "tabs.js").read_text(encoding="utf-8")
    jobs = (ROOT / "server" / "manager" / "web" / "jobs" / "jobs.js").read_text(encoding="utf-8")
    job_detail = (ROOT / "server" / "manager" / "web" / "jobs" / "detail.js").read_text(encoding="utf-8")
    styles = "\n".join(
        (
            ROOT / "server" / "manager" / "web" / relative
        ).read_text(encoding="utf-8")
        for relative in ("styles/app.css", "styles/report.css")
    )

    assert "row.append(...(handle ? [handle] : []), tabButton(tab, nested), tabCloseButton(tab))" in tabs
    assert "button.append(close)" not in tabs
    assert 'button.title = document.body.classList.contains("sidebar-collapsed") ? "" : tab.title;' in tabs
    assert "statusCell(job, context)" in jobs
    list_format = (ROOT / "server" / "manager" / "web" / "jobs" / "list-format.js").read_text(encoding="utf-8")
    assert 'analyzing: "分析中"' in list_format
    assert 'active > 0 ? "analyzing" : job.status' in list_format
    assert "context.isRouteCurrent?.() !== false" in jobs
    assert "context.isRouteCurrent?.() !== false" in job_detail
    assert "payload.public === false" in jobs
    assert "未登录时仅显示服务器公开任务（最多 20 个）" in jobs
    assert "function fieldValue(context, key, value)" in job_detail
    assert "Intl.DateTimeFormat().resolvedOptions().timeZone" in job_detail
    assert ".job-status.succeeded" in styles
    assert ".job-status.failed" in styles
    assert ".job-status.running" in styles
    assert ".job-status.analyzing" in styles
    assert ".job-status.submitted" in styles
    assert "body.sidebar-collapsed .tab-label" in styles
    assert "body.sidebar-collapsed .nav-button,\nbody.sidebar-collapsed .opened-tab" in styles
    assert ".opened-tabs" in styles
    assert "scrollbar-gutter: stable" not in styles
    assert "body.sidebar-collapsed #opened-tabs" in styles
    assert "scrollbar-width: none" in styles
    assert "body.sidebar-collapsed:not(.embedded-presentation) .chapter-rail" in styles
    assert ".component > details > .component-children { margin-left: 20px; padding-left: 0; }" in styles
    assert ".artifact-image { display: block; width: 100%; max-width: 100%; height: auto;" in styles


def test_web_shell_uses_swift_symbol_registry_for_modules_and_references(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(base_url) as response:
            shell = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/core/icons.js") as response:
            icons = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/rich-text.js") as response:
            rich_text = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/rich-text-blocks.js") as response:
            rich_text_blocks = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/table-view.js") as response:
            table_view = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/lazy-runtime.js") as response:
            lazy_runtime = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/component-view.js") as response:
            components = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/chapter-rail.js") as response:
            chapter_rail = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/report-renderer.js") as response:
            renderer = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/coordinator.js") as response:
            research = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/shell.js") as response:
            shell_module = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/report-entry.js") as response:
            report_entry = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/source.js") as response:
            report_source = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/styles/app.css") as response:
            styles = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/styles/report.css") as response:
            styles += "\n" + response.read().decode("utf-8")

    assert '/research-static/core/icons.js' in shell
    assert 'window.FTIcons' in icons
    assert 'chart.xyaxis.line' in icons
    assert 'person.crop.rectangle.stack' in icons
    assert 'FTIcons.reference' in rich_text
    assert 'factortester-local://' in rich_text
    assert '(?:file)' in rich_text
    assert 'return "file"' in rich_text
    assert 'FTIcons.section' in components
    assert 'window.FTReportChapterRail' in chapter_rail
    assert '__ftChapterRailCleanup' in chapter_rail
    assert 'markerCentersDirty' in chapter_rail
    assert 'Math.floor((low + high) / 2)' in chapter_rail
    assert 'rail.addEventListener("scroll", invalidateMarkerCenters' in chapter_rail
    assert 'FTReportComponents' in renderer
    assert 'IntersectionObserver' in lazy_runtime
    assert 'window.FTReportLazyRuntime' in lazy_runtime
    assert 'context.lazyCallbacks' in lazy_runtime
    assert 'function reset(context)' in lazy_runtime
    assert 'lazyRootMargin' in lazy_runtime
    assert 'FTReportLazyRuntime.observe' in components
    assert 'sharedLazyObserver' not in components
    assert 'MAX_ESTIMATE_DEPTH' in components
    assert 'component-body-lazy' in components
    assert 'content_available' in components
    assert 'context.loadComponent' in components
    assert '__ftLazyCleanup' in renderer + research
    assert '__ftChapterRailCleanup' in chapter_rail
    assert '__ftChapterRailCleanup' not in report_entry
    assert '__ftChapterRailCleanup' not in research
    assert 'renderMath' in rich_text
    assert 'renderDisplayMath' in rich_text_blocks
    assert 'FTReportTables.render' in rich_text_blocks
    assert 'window.FTReportTables' in table_view
    assert 'CHUNK_SIZE' in table_view
    assert 'function markdownLinkAt' in rich_text
    assert 'function isFactorAliasToken' in rich_text
    assert 'const parseTableCells = line =>' in rich_text_blocks
    assert '/^:?-+:?$/' in rich_text_blocks
    assert 'cells.length <= count' in rich_text_blocks
    assert 'factorAliasPipe' in rich_text_blocks
    assert 'split(/\\s*\\|\\s*/)' not in rich_text_blocks
    assert 'asset_ref' in components
    assert 'section-bridge' in components
    assert 'captureScrollPosition' in research
    assert 'FTReportEntry' in report_entry
    assert '/index' in report_source
    assert '/chapters/' in report_source
    assert 'loadChapter' in report_source
    assert 'loadComponent' in report_source
    assert 'metadata=1' in report_source
    assert 'chapterDescriptors' in renderer
    assert 'DEFAULT_CHAPTER_CACHE_LIMIT' in renderer
    assert 'FTReportChapterCache' in renderer
    assert 'chapterCache.set' in renderer
    assert 'chapterLoadToken' in renderer
    assert 'dataset.componentKind' in components
    assert 'overflow-x: auto; overflow-y: auto' in styles
    assert 'id="sidebar-toggle"' in shell
    assert 'id="sidebar-resize-handle"' in shell
    assert 'initializeSidebarLayout' in research
    assert 'ft-sidebar-width' in shell_module
    assert 'sidebar-collapsed' in shell_module
    assert 'item.sidebarVisible' in shell_module
    assert 'document.querySelector("#home-brand")' in shell_module
    assert 'tabs.navigate("/")' in shell_module
    assert 'FTNavigation.fallbackModulesForSession' in shell_module
    assert 'max-height: calc(100vh - 180px)' in styles
    assert 'overflow-x: hidden' in styles
    assert '.component > details > .section-bridge' in styles
    assert 'localResourcePath' in rich_text + report_entry
    assert '/assets/' in report_source
    assert 'Generation ${value.generation}' not in research


def test_manager_serves_the_site_icon(tmp_path) -> None:
    icon = (ROOT / "static" / "favicon.svg").read_bytes()
    shell = (ROOT / "server" / "manager" / "web" / "research.html").read_text(
        encoding="utf-8",
    )
    assert '<link rel="icon" type="image/svg+xml" href="/favicon.svg">' in shell
    assert "modules.json" not in icon.decode("utf-8")
    assert "SF Symbols" not in icon.decode("utf-8")

    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        for path in ("/favicon.svg", "/favicon.ico"):
            with urlopen(f"{base_url}{path}") as response:
                assert response.status == 200
                assert response.headers["Content-Type"] == "image/svg+xml"
                assert response.read() == icon


def test_client_module_catalog_keeps_test_routes_out_of_entry_surfaces(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/modules",
            headers={"Authorization": "Bearer user-token"},
        )) as response:
            value = json.loads(response.read())

    modules = {item["id"]: item for item in value["modules"]}
    assert modules["home"]["title_key"] == "主页"
    assert modules["home"]["sidebarVisible"] is True
    assert modules["home"]["homeVisible"] is False
    assert modules["ic-test"]["title_key"] == "IC 测试"
    assert modules["backtest"]["title_key"] == "回测"
    assert modules["ic-test"]["sfSymbol"] == "chart.xyaxis.line"
    assert modules["backtest"]["sfSymbol"] == "chart.line.uptrend.xyaxis"
    for module_id, path in (("ic-test", "/ic-test"), ("backtest", "/backtest")):
        assert modules[module_id]["sidebarVisible"] is False
        assert modules[module_id]["homeVisible"] is False
        assert modules[module_id]["path"] == path
    assert modules["jobs"]["sfSymbol"] == "checklist"
    assert modules["jobs"]["title_key"] == "测试"
    assert modules["jobs"]["path"] == "/jobs?section=types"
    assert modules["products"]["title"] == "产品库"
    assert modules["products"]["title_key"] == "产品库"
    test_tabs = modules["jobs"]["children"]
    assert [item["id"] for item in test_tabs] == ["jobs.types", "jobs.list"]
    assert [item["id"] for item in test_tabs[0]["children"]] == [
        "ic-test", "backtest",
    ]
    assert "single_factor_test" not in modules


def test_manager_navigation_is_role_filtered_and_nests_profiles_under_research(
    tmp_path,
) -> None:
    state = authenticated_state(tmp_path)
    state._sessions[state._token_hash("admin-token")] = (
        "admin@1", "super_admin", float("inf"),
    )
    state._sessions[state._token_hash("org-admin-token")] = (
        "org-admin@1", "org_admin", float("inf"),
    )
    with running_manager(state) as base_url:
        def modules(token):
            with urlopen(Request(
                f"{base_url}/api/modules",
                headers={"Authorization": f"Bearer {token}"},
            )) as response:
                return json.loads(response.read())["modules"]

        user_modules = {item["id"]: item for item in modules("user-token")}
        org_modules = {item["id"]: item for item in modules("org-admin-token")}
        admin_modules = {item["id"]: item for item in modules("admin-token")}

    assert "profiles" not in user_modules
    assert "profiles" not in org_modules
    assert "profiles" not in admin_modules
    assert {
        item["id"] for item in user_modules["research"]["children"]
    } == {
        "research.graph", "research.profiles",
        "research.agent-models", "research.reports", "research.evidence",
    }
    assert "research.researches" not in user_modules["research"]["children"]
    assert any(
        item["id"] == "research.reports"
        for item in user_modules["research"]["children"]
    )
    assert "admin_users" not in user_modules
    assert not {"manager", "sqlite_web"} & set(org_modules)
    assert {"manager", "sqlite_web"} <= set(admin_modules)


def test_legacy_profiles_entry_redirects_to_research_tab(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        response = urlopen(Request(
            f"{base_url}/profiles",
            headers={"Authorization": "Bearer user-token"},
        ))
        assert response.geturl().endswith("/research?section=profiles")


def test_every_home_module_has_bilingual_title_and_description(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    state._sessions[state._token_hash("user-token")] = (
        "user@1", "super_admin", float("inf"),
    )
    headers = {"Authorization": "Bearer user-token"}
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/modules", headers=headers,
        )) as response:
            modules = json.loads(response.read())["modules"]
        localizations = {}
        for locale in ("zh-Hans", "en"):
            with urlopen(Request(
                f"{base_url}/api/localizations/{locale}", headers=headers,
            )) as response:
                localizations[locale] = json.loads(response.read())["strings"]

    cards = [
        item for item in modules
        if item["id"] not in {"home", "settings"}
    ]
    assert cards
    research = next(item for item in cards if item["id"] == "research")
    assert next(item for item in research["children"] if item["id"] == "research.profiles")[
        "title_key"
    ] == "研究身份"
    for module in cards:
        assert module.get("description_key"), module["id"]
        for locale, strings in localizations.items():
            assert module["title_key"] in strings, (locale, module["id"], "title")
            assert module["description_key"] in strings, (
                locale, module["id"], "description",
            )

    coordinator = (
        ROOT / "server" / "manager" / "web" / "app" / "coordinator.js"
    ).read_text(encoding="utf-8")
    assert "module.description_key" in coordinator
    assert "function moduleDescription" not in coordinator


def test_manager_module_manifest_is_public_and_keeps_manager_only_entries(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/static/config/modules.json") as response:
            manifest = json.loads(response.read())

    modules = {item["id"]: item for item in manifest["modules"]}
    assert modules["home"]["title"] == "主页"
    assert modules["home"]["sidebarVisible"] is True
    assert modules["home"]["homeVisible"] is False
    assert modules["jobs"]["title"] == "测试"
    assert modules["jobs"]["path"] == "/jobs?section=types"
    assert "ic-test" not in modules
    assert "backtest" not in modules
    assert modules["sqlite_web"]["title"] == "数据库"
    assert modules["sqlite_web"]["managerOnly"] is True
    assert modules["sqlite_web"]["homeOnly"] is True
    assert modules["docs"]["managerOnly"] is True
    assert modules["docs"]["homeOnly"] is True
    assert modules["server_operations"]["managerOnly"] is True
    assert modules["server_operations"]["homeOnly"] is True


def test_manager_home_only_modules_use_distinct_symbols(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    state._sessions[state._token_hash("user-token")] = (
        "user@1", "super_admin", float("inf"),
    )
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/core/icons.js") as response:
            icons = response.read().decode("utf-8")
        with urlopen(Request(
            f"{base_url}/api/modules",
            headers={"Authorization": "Bearer user-token"},
        )) as response:
            modules = {item["id"]: item for item in json.loads(response.read())["modules"]}

    assert modules["sqlite_web"]["sfSymbol"] == "cylinder.split.1x2"
    assert modules["docs"]["sfSymbol"] == "book"
    assert 'docs: "book"' in icons
    assert 'sqlite_web: "cylinder.split.1x2"' in icons
    assert '"book":' in icons
    assert '"cylinder.split.1x2":' in icons


def test_manager_serves_docs_shell_without_a_service_login(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    calls = []

    def request(**values):
        calls.append(values)
        return manager.GatewayResponse(
            status=200,
            body=b"<html>docs</html>",
            content_type="text/html",
        )

    monkeypatch.setattr(state.gateway, "request", request)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/docs?presentation=embedded") as response:
            body = response.read()

    assert body.startswith(b"<!doctype html>")
    assert b"FT_STATIC_SCRIPTS" not in body
    assert calls == []


def test_sqlite_web_requires_login_but_accepts_manager_cookie(tmp_path, monkeypatch) -> None:
    state = authenticated_state(tmp_path)
    gateway_calls = []
    sqlite_calls = []

    def gateway_request(**values):
        gateway_calls.append(values)
        raise AssertionError("SQLite Web must not use a business service port")

    def sqlite_request(**values):
        sqlite_calls.append(values)
        return manager.ManagerSQLiteResponse(
            status=200,
            body=b"<html>sqlite</html>",
            content_type="text/html",
        )

    monkeypatch.setattr(state.gateway, "request", gateway_request)
    monkeypatch.setattr(state.sqlite_web, "request", sqlite_request)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/sqlite-web/") as response:
            shell = response.read()
            assert response.status == 200
        assert b"<html" in shell
        with urlopen(f"{base_url}/sqlite-web/?presentation=embedded") as response:
            embedded_shell = response.read()
            assert response.status == 200
        assert b"<html" in embedded_shell
        request_value = Request(
            f"{base_url}/sqlite-web/?presentation=embedded",
            headers={"Cookie": "ft-manager-session=user-token"},
        )
        with urlopen(request_value) as response:
            assert response.read() == b"<html>sqlite</html>"

    assert gateway_calls == []
    assert len(sqlite_calls) == 1
    assert {
        key: sqlite_calls[0][key]
        for key in ("method", "path", "query", "principal")
    } == {
        "method": "GET",
        "path": "/sqlite-web/",
        "query": "presentation=embedded",
        "principal": "user@1",
    }
    assert sqlite_calls[0]["body"] == b""


def test_manager_client_restores_all_native_service_controls(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/settings/manager.js") as response:
            script = response.read().decode("utf-8")

    for expected in (
        "/start", "/stop", "/restart-api", "/restart-bundle",
        "/force-stop", "/vibe/start", "/vibe/stop",
        "本机打开", "局域网打开",
    ):
        assert expected in script


def test_web_job_detail_keeps_typed_artifact_and_live_progress_features(
    tmp_path,
) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/jobs/jobs.js") as response:
            jobs = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/jobs/detail.js") as response:
            job_detail = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/jobs/actions.js") as response:
            actions = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/jobs/artifacts.js") as response:
            artifacts = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/jobs/progress.js") as response:
            progress = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/jobs/generation.js") as response:
            generation = response.read().decode("utf-8")
        with urlopen(
            f"{base_url}/research-static/jobs/job-artifact-viewers.js"
        ) as response:
            viewers = response.read().decode("utf-8")
    coordinator = (
        ROOT / "server" / "manager" / "web" / "app" / "coordinator.js"
    ).read_text(
        encoding="utf-8",
    )

    assert "/stream" in progress
    assert "updateActiveTab" in job_detail
    assert "window.FTJobs.detail = detail" in job_detail
    assert "window.FTJobs.configuration = configuration" in job_detail
    assert "在配置页面打开" in job_detail
    assert "FTRunSpecView.load" in job_detail
    assert "FTRunSpecView.render" in job_detail
    assert "FTReferencePage.routeFor" in job_detail
    assert "runspec:sha256:" in job_detail
    assert "FTJobActions.install" in job_detail
    assert "window.FTJobActions" in actions
    assert 'job.status === "awaiting_confirmation"' in actions
    assert 'add("下一步", "continue"' in actions
    assert 'add("运行到底", "continue"' in actions
    assert "cancelButton" in actions
    assert 'actionPath(jobID, "cancel", portQuery)' in actions
    run_batch = (
        ROOT / "server" / "manager" / "web" / "workbench" / "test-run-batch.js"
    ).read_text(
        encoding="utf-8",
    )
    assert "FTJobActions?.cancelButton" in run_batch
    assert 'context.button(context.t("查看测试任务")' in run_batch
    assert 'add("按冻结配置重试", "retry"' not in actions
    assert "恢复为可编辑配置" not in actions
    assert 'method: "DELETE"' in artifacts
    assert "showDirectoryPicker" in artifacts
    assert "/artifacts/archive" not in artifacts
    assert "equity_curve" in artifacts
    assert "FTJobArtifactViewers.mount" in artifacts
    assert "job.execution_server_id || job.server_id" in jobs
    assert "job.execution_port" in jobs
    assert "function executionTarget" in job_detail
    assert "context.showNotice?.(" in artifacts
    assert "api, raw, navigate, openTab, activeNav" in coordinator
    assert "priceChart" in viewers
    assert "dataTable" in viewers
    assert "tableModel" in viewers
    assert "column_presentations" in viewers
    assert "FTReportTables.render" in viewers
    assert "artifact-image" in viewers
    assert "media_type" in viewers
    assert "FTJobArtifacts.fetch" in viewers
    assert "/artifacts/${encodeURIComponent(artifact.name)}" in viewers
    assert "/preview" not in viewers
    assert "/api/jobs/artifact-capabilities" in generation
    assert "/supplementals" in generation
    assert "report_output_generation" in generation
    assert "output_requests" in generation


def test_web_auth_switches_between_login_and_registration_forms(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_ALLOW_PUBLIC_REGISTRATION", "0")
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/research.html") as response:
            html = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/coordinator.js") as response:
            script = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/auth.js") as response:
            auth_script = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/styles/app.css") as response:
            styles = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/styles/report.css") as response:
            styles += "\n" + response.read().decode("utf-8")

    assert 'id="login-form"' in html
    assert 'id="register-form" hidden' in html
    assert 'name="ft-registration-enabled" content="0"' in html
    assert "FTAuth.bind" in script
    assert 'showAuthForm("register")' in auth_script
    assert 'registerButton.hidden = !registrationEnabled' in auth_script
    assert 'showAuthForm("login")' in auth_script
    assert "form[hidden]" in styles


def test_web_factor_library_reads_product_group_owned_subject_relations(
    tmp_path,
) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        scripts = {}
        for name in [
            "factor-model", "factor-list", "factor-details", "factors",
            "factor-catalog-runtime", "factor-catalog-list",
        ]:
            with urlopen(
                f"{base_url}/research-static/catalog/{name}.js"
            ) as response:
                scripts[name] = response.read().decode("utf-8")

    model = scripts["factor-model"]
    listing = scripts["factor-list"]
    details = scripts["factor-details"]
    coordinator = scripts["factors"]
    runtime = scripts["factor-catalog-runtime"]
    catalog_list = scripts["factor-catalog-list"]
    assert "group.factor_refs" in model
    assert "group.factor_set_refs" in model
    assert "value.product_group_refs" not in model
    assert "item.value.target_ref, item.value.set_ref" in model
    assert 'context.api(`/api/factor-library/families${suffix}`)' in runtime
    assert 'context.api("/api/factor-library/factor-sets")' in runtime
    assert "/api/factor-library/factor-sets/detail" in details
    assert "servicePath" not in coordinator
    assert "/api/entities/factor-sets" not in coordinator
    assert "/api/product-library/product-groups" in runtime
    assert "factorTesterLocalFactorSets" not in runtime
    assert 'context.t("因子家族")' in listing
    assert 'context.t("因子")' in listing
    assert 'context.t("因子集合")' in listing
    assert '"/factors/sets"' in listing
    assert "FTUI.pagedTable" in listing
    assert 'className = "factor-catalog-controls"' in catalog_list
    assert 'className = "ft-multi-select-filter factor-catalog-search-control"' in catalog_list
    assert "context.toolbar.append(\n      search" not in catalog_list
    assert 'context.t("按下级用户筛选")' in catalog_list
    assert "model().withSourceMetadata" in details
    assert "FTFactorDetailShared.loadSourceVersion" in details


def test_test_workbench_reads_factor_candidates_from_manager_catalog(
    tmp_path,
) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        scripts = {}
        for name in (
            "tests", "test-factors", "factor-selection", "test-configuration",
            "test-configuration-compiler",
        ):
            with urlopen(
                f"{base_url}/research-static/workbench/{name}.js"
            ) as response:
                scripts[name] = response.read().decode("utf-8")

    script = scripts["tests"]
    assert 'context.api("/api/factor-library/factors")' in script
    assert (
        'context.api("/api/product-library/product-groups?view=summary"' in script
    )
    assert '/custom-factors/api/client/factor-library' not in script
    assert 'servicePath("/api/product-groups")' not in script
    assert "return_freq" not in scripts["test-configuration-compiler"]
    assert "test-factor-return-frequency" not in scripts["test-factors"]
    assert "setReturnFrequency" not in scripts["factor-selection"]
    assert 'control.className = "json-code json-editor"' in (
        ROOT / "server" / "manager" / "web" / "workbench" / "test-setting-fields.js"
    ).read_text(encoding="utf-8")


def test_ic_product_group_selection_preserves_every_selected_path() -> None:
    product_selection = (
        ROOT / "server" / "manager" / "web" / "workbench" / "test-products.js"
    )
    program = f"""
global.window = globalThis;
eval(require("fs").readFileSync({json.dumps(str(product_selection))}, "utf8"));
const state = {{
  kind: "ic",
  groups: [
    {{id: "day", name: "日盘", paths: ["day-path"]}},
    {{id: "night", name: "夜盘", paths: ["night-path"]}},
  ],
  values: {{product_path_selections: []}},
  groupRef: "",
  groupRefs: FTTestProducts.restoreReferences(
    {{product_path_selections: [{{product_path_selection_id: "night"}}]}},
    {{product_group_refs: ["day", "night"]}},
  ),
}};
FTTestProducts.synchronize(state);
const before = FTTestProducts.selectedProjections(state);
FTTestProducts.setSelected(state, state.groups[1], false);
console.log(JSON.stringify({{
  restored: before.map(item => item.product_path_selection_id),
  paths: before.map(item => item.selected_paths),
  remaining: state.values.product_path_selections.map(
    item => item.product_path_selection_id,
  ),
}}));
"""
    result = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True, text=True,
    )
    assert json.loads(result.stdout) == {
        "restored": ["day", "night"],
        "paths": [["day-path"], ["night-path"]],
        "remaining": ["day"],
    }


def test_ic_category_selection_preserves_candidates_and_default() -> None:
    category_selection = (
        ROOT / "server" / "manager" / "web" / "workbench" / "test-categories.js"
    )
    program = f"""
global.window = globalThis;
eval(require("fs").readFileSync({json.dumps(str(category_selection))}, "utf8"));
const state = {{
  kind: "ic",
  values: {{
    category: "行业",
    category_candidates: [
      {{name: "行业", enabled: true}},
      {{name: "日夜盘", enabled: true}},
    ],
  }},
}};
FTTestCategories.setEnabled(state, state.values.category_candidates[0], false);
FTTestCategories.setCategory(state, state.values.category_candidates[1]);
console.log(JSON.stringify({{
  selected: state.values.category,
  enabled: FTTestCategories.candidates(state).map(item => item.enabled),
}}));
"""
    result = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True, text=True,
    )
    assert json.loads(result.stdout) == {
        "selected": "日夜盘",
        "enabled": [False, True],
    }


def test_backtest_group_model_preserves_hierarchy_and_combinations() -> None:
    group_model = (
        ROOT / "server" / "manager" / "web" / "workbench"
        / "backtest-group-model.js"
    )
    batch_module = group_model.with_name("backtest-group-batches.js")
    program = f"""
global.window = globalThis;
global.FTTestProducts = {{
  groupID: value => value?.id || value?.product_path_selection_id || "",
  groupLabel: value => value?.name || value?.label || value?.id || "",
  projection: value => ({{
    product_path_selection_id: value.id,
    label: value.name,
    selected_paths: value.paths || [],
  }}),
}};
eval(require("fs").readFileSync({json.dumps(str(batch_module))}, "utf8"));
eval(require("fs").readFileSync({json.dumps(str(group_model))}, "utf8"));
const state = {{analysis: {{groups: [], ls_configs: []}}}};
const roots = FTBacktestGroupModel.addBaseBatch(state, {{
  product_path_selection: {{id: "day", name: "日盘", paths: ["day-path"]}},
  factor_candidate_refs: ["FactorA"], splitCount: 3, groupIndex: 1, allGroups: true,
}});
const child = FTBacktestGroupModel.addDerived(state, roots[0].id, {{
  name: "硅派生组", productMask: ["SI.GFE"],
  overrides: {{position_policy: "buy_and_hold"}},
}});
const combination = FTBacktestGroupModel.addLongShort(
  state, child.id, roots[2].id, "硅多空",
);
const before = {{
  rootNames: roots.map(group => group.name),
  childParent: child.parentId,
  childMask: child.productMask,
  childOverride: child.position_policy,
  combination: [combination.longGroupId, combination.shortGroupId],
}};
state.selectedBacktestGroupIDs = [roots[0].id];
FTBacktestGroupModel.removeSelected(state);
console.log(JSON.stringify({{
  before,
  remainingNames: state.analysis.groups.map(group => group.name),
  remainingCombinations: state.analysis.ls_configs.length,
}}));
"""
    result = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True, text=True,
    )
    value = json.loads(result.stdout)
    assert all(
        name.startswith("batch:1/bg_")
        for name in value["before"]["rootNames"]
    )
    assert value["before"]["childParent"].startswith("bg_")
    assert value["before"]["childMask"] == {"SI.GFE": True}
    assert value["before"]["childOverride"] == "buy_and_hold"
    assert value["before"]["combination"][0].startswith("dg_")
    assert value["before"]["combination"][1].startswith("bg_")
    assert all(
        name.startswith("batch:1/bg_")
        for name in value["remainingNames"]
    )
    assert value["remainingCombinations"] == 0


def test_backtest_configuration_freezes_groups_products_and_all_factors() -> None:
    source = (
        ROOT / "server" / "manager" / "web" / "workbench"
        / "test-configuration.js"
    ).read_text(encoding="utf-8")

    assert "state.analysis?.groups" in source
    assert "product_selections: productSelections" in source
    assert "ls_configs: prior.ls_configs || []" in source


def test_reserved_self_profile_is_marked_only_in_the_outer_directory() -> None:
    profile_root = ROOT / "server" / "manager" / "web" / "profile"
    profiles = (profile_root / "profiles.js").read_text(encoding="utf-8")
    directory = (profile_root / "profile-directory.js").read_text(
        encoding="utf-8",
    )
    detail = (profile_root / "profile-directory-detail.js").read_text(
        encoding="utf-8",
    )
    styles = (
        ROOT / "server" / "manager" / "web" / "styles" / "app.css"
    ).read_text(encoding="utf-8")

    assert 'identifier === "self"' in profiles
    assert "profile-self-badge" in profiles
    assert "profile-directory-row-self" in directory
    assert "profile-self-badge" in directory
    assert "profile-directory-detail-self" not in detail
    assert "profile-self-badge" not in detail
    assert ".profile-directory-row-self" in styles


def test_profile_detail_exposes_skills_and_embeds_runtime_binding_in_overview() -> None:
    profile_root = ROOT / "server" / "manager" / "web" / "profile"
    profiles = (profile_root / "profiles.js").read_text(encoding="utf-8")
    detail = (profile_root / "profile-directory-detail.js").read_text(
        encoding="utf-8",
    )

    assert '["skills", "技能管理"]' in profiles
    assert '["skills", "技能管理"]' in detail
    assert '["binding", "运行绑定"]' not in profiles
    assert '["binding", "运行绑定"]' not in detail
    assert "root.append(binding(context, profile))" in detail
    assert "FTAgentSkills.render" in detail


def test_manager_factor_catalog_does_not_select_a_service_port(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state.client_state, "factor_library",
        lambda principal: {
            "principal": principal,
            "factors": [{"factor_ref": "factor:one"}],
            "families": [{"family_ref": "factor-family:one"}],
        },
    )
    monkeypatch.setattr(
        state.client_state, "factor_sets",
        lambda principal, query="": [{
            "target_ref": "factor-set:one",
            "owner_username": principal,
            "query": query,
        }],
    )
    monkeypatch.setattr(
        state.client_state, "factor_set_detail",
        lambda principal, target_ref, **_values: {
            "target_ref": target_ref, "owner_username": principal,
        },
    )
    monkeypatch.setattr(
        state.client_state, "factor_set_descriptor",
        lambda principal, target_ref: {
            "target_ref": target_ref,
            "manifest": {"owner_username": principal},
        },
    )

    def reject_service(*_args, **_values):
        raise AssertionError("Manager factor catalog must not use a service port")

    monkeypatch.setattr(state.gateway, "request", reject_service)
    monkeypatch.setattr(state, "preferred_service_port", reject_service)
    monkeypatch.setattr(state, "service_ports", reject_service)
    headers = {"Authorization": "Bearer user-token"}
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/factor-library/families", headers=headers,
        )) as response:
            families = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/factor-library/factors", headers=headers,
        )) as response:
            factors = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/factor-library/factor-sets?query=momentum",
            headers=headers,
        )) as response:
            sets = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/factor-library/factor-sets/detail?target_ref=factor-set%3Aone",
            headers=headers,
        )) as response:
            detail = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/factor-library/factor-sets/descriptor?target_ref=factor-set%3Aone",
            headers=headers,
        )) as response:
            descriptor = json.loads(response.read())

    assert families["principal"] == "user@1"
    assert families["families"][0]["family_ref"] == "factor-family:one"
    assert factors["factors"][0]["factor_ref"] == "factor:one"
    assert sets["items"][0]["query"] == "momentum"
    assert detail["factor_set"]["target_ref"] == "factor-set:one"
    assert descriptor["descriptor"]["target_ref"] == "factor-set:one"


def test_manager_factor_source_manifest_does_not_select_a_service_port(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    calls = []
    monkeypatch.setattr(
        FactorSourceManifest,
        "build",
        lambda _manifest, principal, **options: calls.append(
            (principal, options)
        ) or {
            "success": True,
            "server_id": options["server_id"],
            "principal": principal,
            "items": [],
        },
    )
    monkeypatch.setattr(
        state.gateway, "request",
        lambda **_values: pytest.fail("source manifest must stay in Manager"),
    )
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/factor-library/family-sources/manifest"
            "?include_subordinates=0",
            headers={"Authorization": "Bearer user-token"},
        )) as response:
            value = json.loads(response.read())

    assert value["principal"] == "user@1"
    assert calls == [("user@1", {
        "server_id": state.server_id,
        "include_subordinates": False,
    })]


def test_manager_factor_library_provenance_does_not_select_a_service_port(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    catalog = {
        "factors": [{
            "factor_alias": "Momentum|N:3m",
            "owner_username": "user@1",
            "owner_alias": "User",
            "product_group": "CNFutures",
            "source_code": "must not cross the control plane",
        }],
    }
    monkeypatch.setattr(
        state.federated_public_data,
        "factor_library",
        lambda principal: catalog if principal == "user@1" else {},
    )
    monkeypatch.setattr(
        state.gateway,
        "request",
        lambda **_values: pytest.fail("provenance must stay in Manager"),
    )
    headers = {"Authorization": "Bearer user-token"}
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/factor-library/owners",
            headers=headers,
        )) as response:
            owners = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/factor-library/owners/"
            "user%401/projection?product_group=CNFutures",
            headers=headers,
        )) as response:
            projection = json.loads(response.read())

    assert owners["sources"][0]["owner_ref"] == "user@1"
    assert projection["projection"]["factors"] == [{
        "factor_alias": "Momentum|N:3m",
        "owner_username": "user@1",
        "owner_alias": "User",
        "product_group": "CNFutures",
    }]
    assert "source_code" not in json.dumps(projection)


def test_manager_validates_report_references_without_a_service_port(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state.gateway,
        "request",
        lambda **_values: pytest.fail("reference validation must stay in Manager"),
    )
    target = "Product/Futures/CNFutures/_products/SI.GFE"
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/report-references/validate"
            f"?kind=product&target_ref={quote(target, safe='')}",
            headers={"Authorization": "Bearer user-token"},
        )) as response:
            value = json.loads(response.read())

    assert value["reference"]["target_ref"] == target


def test_manager_factor_set_writes_do_not_select_a_service_port(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    calls = []
    monkeypatch.setattr(
        factor_set_registry,
        "author_factor_set",
        lambda principal, definition, **options: calls.append(
            ("author", principal, definition, options)
        ) or {"target_ref": "factor-set:new"},
    )
    monkeypatch.setattr(
        factor_set_registry,
        "unregister_factor_set",
        lambda principal, target_ref: calls.append(
            ("delete", principal, target_ref)
        ) or True,
    )
    monkeypatch.setattr(
        state.gateway, "request",
        lambda **_values: pytest.fail("Factor Set writes must stay in Manager"),
    )
    headers = {
        "Authorization": "Bearer user-token",
        "Content-Type": "application/json",
    }
    with running_manager(state) as base_url:
        body = json.dumps({
            "persist": True,
            "definition": {
                "set_id": "new", "alias": "New", "members": [{}],
            },
        }).encode()
        with urlopen(Request(
            f"{base_url}/api/factor-library/factor-sets",
            data=body,
            headers=headers,
            method="POST",
        )) as response:
            created = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/factor-library/factor-sets?target_ref=factor-set%3Anew",
            headers=headers,
            method="DELETE",
        )) as response:
            deleted = json.loads(response.read())

    assert created["factor_set"]["target_ref"] == "factor-set:new"
    assert deleted["success"] is True
    assert calls[0][0:2] == ("author", "user@1")
    assert calls[1] == ("delete", "user@1", "factor-set:new")


def test_manager_factor_set_detail_allows_only_a_direct_child(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state.client_state,
        "factor_set_scopes",
        lambda principal, query="": {
            "mine": [],
            "subordinates": [{
                "target_ref": "factor-set:child",
                "owner_username": "child@1",
            }],
        },
    )
    monkeypatch.setattr(
        state.client_state,
        "factor_set_detail",
        lambda principal, target_ref, **_values: {
            "target_ref": target_ref, "owner_username": principal,
        },
    )
    headers = {"Authorization": "Bearer user-token"}
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/factor-library/factor-sets/detail"
            "?target_ref=factor-set%3Achild&owner_username=child%401",
            headers=headers,
        )) as response:
            child = json.loads(response.read())
        with pytest.raises(HTTPError) as forbidden:
            urlopen(Request(
                f"{base_url}/api/factor-library/factor-sets/detail"
                "?target_ref=factor-set%3Ahidden&owner_username=peer%401",
                headers=headers,
            ))

    assert child["factor_set"]["owner_username"] == "child@1"
    assert forbidden.value.code == 403


def test_web_catalog_profile_and_settings_ignore_stale_async_responses(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        paths = {
            "catalog": "/research-static/catalog/products.js",
            "catalog_details": "/research-static/catalog/details.js",
            "factors": "/research-static/catalog/factors.js",
            "factor_runtime": "/research-static/catalog/factor-catalog-runtime.js",
            "profiles": "/research-static/profile/profiles.js",
            "settings": "/research-static/settings/settings.js",
        }
        scripts = {}
        for name, path in paths.items():
            with urlopen(f"{base_url}{path}") as response:
                scripts[name] = response.read().decode("utf-8")

    for name, script in scripts.items():
        if name == "factors":
            continue
        assert "context.isRouteCurrent?.() !== false" in script
    assert "context.isRouteCurrent?.() !== false" in scripts["factor_runtime"]
    assert "const payload = await context.api(\"/api/client/profiles\")" in scripts["profiles"]
    assert "runtime_kind" in scripts["profiles"]
    assert "/api/client/profile-claims" in scripts["profiles"]
    assert 'const embedded = Boolean(options.embedded)' in scripts["profiles"]
    assert '尚无已注册研究身份' in scripts["profiles"]
    assert '尚无已注册 Profile。可在下方创建，注册完成后会立即显示。' in scripts["profiles"]
    assert 'context.api("/api/client/profiles/create"' in scripts["profiles"]
    assert '创建独立 Profile' in scripts["profiles"]
    assert 'context.navigate(`/profiles/${profileID}`)' in scripts["profiles"]
    assert "const payload = await context.api(\"/api/client/workspace\")" in scripts["settings"]
    assert "if (!current(context)) return;" in scripts["catalog_details"]


def test_web_research_exposes_local_download_shared_and_graph_pages(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(
            f"{base_url}/research-static/research/workspaces.js"
        ) as response:
            workspaces = response.read().decode("utf-8")
        with urlopen(
            f"{base_url}/research-static/research/local.js"
        ) as response:
            local_page = response.read().decode("utf-8")
        with urlopen(
            f"{base_url}/research-static/research/shared.js"
        ) as response:
            shared_page = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/coordinator.js") as response:
            shell = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/research/graph.js") as response:
            graph = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/research/graph-list.js") as response:
            graph_list = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/research/reports.js") as response:
            reports = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/research/researches.js") as response:
            researches = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/profile/agent-models.js") as response:
            agent_models = response.read().decode("utf-8")
        with urlopen(
            f"{base_url}/research-static/profile/agent-model-editor.js"
        ) as response:
            agent_model_editor = response.read().decode("utf-8")
        with urlopen(
            f"{base_url}/research-static/profile/profile-directory.js"
        ) as response:
            profile_directory = response.read().decode("utf-8")
        with urlopen(
            f"{base_url}/research-static/profile/profile-directory-detail.js"
        ) as response:
            profile_directory_detail = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/jobs/jobs.js") as response:
            jobs = response.read().decode("utf-8")

    assert '["researches", "研究"]' in workspaces
    assert '["graph", "研究图"]' in workspaces
    assert '["agent-models", "智能体模型"]' in workspaces
    assert 'FTAgentModels.list' in workspaces
    assert "FTResearchCatalog.render({...context, content: body}, body)" in workspaces
    assert "FTResearchGraphList.render(context, body)" in workspaces
    assert "window.FTResearchLocal" in local_page
    assert "clientDownload(context" in local_page
    assert "window.FTResearchShared" in shared_page
    assert "resolvePublicationSource(item, localByReportID, embedded)" in shared_page
    assert "window.FTResearchGraph" in graph
    assert "async function render(context, mount)" in graph
    assert "FTUI.pagedTable" in graph_list
    assert "FTMultiSelectFilter.create" in graph_list
    assert 'path("/user-library/subordinates")' in graph_list
    assert "research-graphs/${encodeURIComponent" in graph_list
    assert "FTUI.pagedTable" in reports
    assert "我的研究报告" in reports
    assert "下级用户的研究报告" in reports
    assert "共享研究报告" in reports
    assert "clientDownload" in reports
    assert "loadClientRelease" in reports
    assert 'search.type = "search"' in agent_models
    assert 'search.addEventListener("input"' in agent_models
    assert "requestAnimationFrame" in agent_models
    assert 'onPageChange,' in agent_models
    assert "FTAgentModelEditor.open" in agent_models
    assert "/duplicate`" in agent_models
    assert "window.FTAgentModelEditor" in agent_model_editor
    assert 'model.addEventListener("focus"' in agent_model_editor
    assert "clientDownload?.(context, release)" in reports
    assert 'section.className = "research-client-download-action"' in local_page
    assert "window.FTResearchCatalog" in researches
    assert "FTUI.pagedTable" in researches
    assert "/api/research" in researches
    assert "card.append(note, downloadChoices(context, value))" in local_page
    assert 'section.className = "job-section client-download"' not in local_page
    assert 'note.className = "secondary research-graph-list-note"' in graph_list
    assert "source_server_ids" in profile_directory
    assert "直属下级研究身份的 Agent 会话默认对直属上级只读可见" in profile_directory_detail
    assert "profile-conversation-sharing" not in profile_directory_detail
    assert "FTUI.pagedTable" in agent_models
    assert "agent-model-dialog" in agent_model_editor
    assert "testExisting" in agent_models
    assert "FTTestPageTabs.render(context, \"tasks\")" in jobs
    assert 'get("presentation") === "embedded"' in workspaces
    assert 'context.toolbar.append(tabBar(context, selected, embedded))' in workspaces
    assert "sectionTabs: tabBar" in workspaces
    assert 'messageHandlers.researchNavigation.postMessage' in workspaces
    assert 'path: `/research?section=${encodeURIComponent(id)}`' in workspaces
    assert 'body.append(FTUI.loading(context.t("正在读取研究…")))' in workspaces
    assert 'context.content.replaceChildren(body)' in workspaces
    assert 'context.navigate(`/profiles/${encodeURIComponent(profileID)}`)' in workspaces
    assert 'await FTProfiles.list({...context, content: body}, {embedded: true})' in workspaces
    assert 'url.searchParams.delete("profile")' in workspaces
    assert 'context.isRouteCurrent?.() === false' in local_page
    assert 'context.isRouteCurrent?.() === false' in shared_page
    assert 'context.isRouteCurrent?.() !== false' in graph
    assert "body.replaceChildren();" in workspaces
    assert 'context.content.append(body)' not in workspaces
    assert "clientDownload(context" in local_page
    assert "if (!embedded || !context.session) return" in local_page
    assert 'context.api("/api/client/research")' in local_page
    assert "embedded && context.session" in shared_page
    assert "item?.is_owned !== true" in workspaces
    assert "local_source: true" in workspaces
    assert 'context.content.replaceChildren(...(embedded ? [] : [tabBar(context, selected)]))' not in workspaces
    assert "/api/public-research" in shared_page
    assert "workPackage" not in workspaces
    assert "research-graphs" not in shell
    assert 'parts[1] === "work"' not in shell
    assert "const pinnedModule = isPinnedPath(initial) ? moduleForPath(initial) : null" in shell
    assert "!tab.closable && tab.id === pinnedModule.id" in shell
    assert 'else if (!isPinnedPath(initial))' in shell


def test_research_workspace_source_resolution_fixture() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "research_publication_source.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_product_library_uses_header_switch_and_tree(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/catalog/products.js") as response:
            script = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/catalog/source-list.js") as response:
            source_script = response.read().decode("utf-8")
        with urlopen(
            f"{base_url}/research-static/catalog/source-family-detail.js"
        ) as response:
            source_family_script = response.read().decode("utf-8")

    assert '["sources", "数据源"]' in script
    assert '["products", "产品"]' in script
    assert '["categories", "产品分类"]' in script
    assert '["groups", "产品组"]' in script
    assert "includeProducts" in script
    assert "/api/product-library/categories" in script
    assert 'if (!query)' in script
    assert 'sourceList' in script
    assert 'FTProductSources.list' in script
    assert 'dataModesCell' in source_script
    assert 'frequencyCell' in source_script
    assert 'product_paths' in source_script
    assert 'product-source-page' in source_script
    assert '/api/product-library/data-sources' in source_script
    assert 'if (localCatalogAvailable())' in source_script
    assert '/api/client/product_sources' in source_script
    assert 'Web 端只能访问服务器提供的数据源' in source_script
    assert 'hasLocalCatalog' in script
    assert 'Manager 提供的产品、合约与行情目录' not in source_script
    assert 'categoryPayload.default_category_id' not in script
    assert 'localStorage.getItem(categoryStorageKey) || ""' in script
    assert "FTProductTree.categorySelectionValues" in script
    assert 'query.append("category", value)' in script
    assert 'product-source-tabs' not in script
    assert '/api/product-library/categories' in script
    assert 'servicePath("/api/internal/product-library/tree")' not in script
    assert '`/api/product-library/tree?${query}`' in script
    assert 'FTProductCategoryModel.availableSourceIDs' in script
    assert 'selectedSources.forEach' in script
    assert 'FTProductTree.render' in script
    assert 'let selectedIDs = FTProductTree.categorySelectionValues' in script
    assert 'selectedIDs = FTProductTree.categorySelectionValues' in script
    assert 'await renderTree()' in script
    assert 'product-category-management-actions product-group-management-actions' in script
    assert 'context.toolbar.append(search, refresh);' in script
    assert 'const showWriteActions = !context.session || source !== "local";' in script
    assert 'rejectProductGroupWrite' in script
    assert 'root.append(productGroupManagementActions(context, source));' in script
    assert 'context.toolbar.append(context.button(' not in script
    assert 'descriptors.find(([, item])' in source_family_script
    assert 'const descriptor = entry?.[1]' in source_family_script


def test_product_catalog_lazy_page_forwards_search_and_paging(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        catalog_routes, "product_library_source_ids",
        lambda _query: ("Synthetic",),
    )
    monkeypatch.setattr(
        state.client_state, "product_names", lambda *_: [
            {"name": "ALPHA.X", "desc": "Alpha", "source_ids": ["Synthetic"]},
            {"name": "BETA.X", "desc": "Beta", "source_ids": ["Synthetic"]},
        ],
    )
    calls = []

    def contract_page(path, category, sources, principal, **values):
        calls.append((path, category, list(sources), principal, values))
        return {
            "nodes": [{"title": "BETA.X"}], "page": values["page"],
            "limit": values["limit"], "total": 1, "total_pages": 1,
            "has_more": False,
        }

    monkeypatch.setattr(state.client_state, "contract_tree_page", contract_page)
    headers = {"Authorization": "Bearer user-token"}
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/product-library/products?query=beta&page=1&limit=1",
            headers=headers,
        )) as response:
            products = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/product-library/contract-tree?path=Product%2F_products"
            "&query=beta&page=2&limit=10",
            headers=headers,
        )) as response:
            leaves = json.loads(response.read())

    assert [item["name"] for item in products["products"]] == ["BETA.X"]
    assert products["total"] == 1
    assert leaves["nodes"] == [{"title": "BETA.X"}]
    assert calls == [(
        "Product/_products", "", ["Synthetic"], "user@1", {
            "query": "beta", "page": 2, "limit": 10,
        },
    )]


def test_manager_product_catalog_does_not_select_a_service_port(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state.client_state, "product_sources",
        lambda: [{"id": "Local", "source_kind": "server"}],
    )
    monkeypatch.setattr(
        state.client_state, "product_tree",
        lambda category, source_ids, principal="": [{
            "title": category or "Product",
            "source_ids": list(source_ids),
            "origin": "server",
        }],
    )
    monkeypatch.setattr(
        state.client_state, "product_contracts",
        lambda name, **_values: {"success": True, "product": name},
    )
    monkeypatch.setattr(
        state.client_state, "product_price_series",
        lambda payload: {"success": True, "product": payload["product_name"]},
    )
    monkeypatch.setattr(
        state.client_state, "product_groups",
        lambda principal: [{
            "name": "候选组", "principal": principal, "catalog_origin": "server",
        }],
    )
    monkeypatch.setattr(
        state.client_state, "create_product_group",
        lambda principal, name, paths, category_ids=None, **_metadata: {
            "group_ref": "product-group:created",
            "name": name,
            "paths": paths,
            "category_ids": category_ids or [],
            "principal": principal,
        },
    )

    def reject_gateway(**_values):
        raise AssertionError("Manager catalog must not use a service port")

    def reject_service_port(*_args, **_values):
        raise AssertionError("Manager catalog must not inspect service ports")

    monkeypatch.setattr(state.gateway, "request", reject_gateway)
    monkeypatch.setattr(state, "preferred_service_port", reject_service_port)
    monkeypatch.setattr(state, "service_ports", reject_service_port)
    headers = {"Authorization": "Bearer user-token"}
    with running_manager(state) as base_url:
        with urlopen(Request(f"{base_url}/api/product-library/data-sources", headers=headers)) as response:
            sources = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/product-library/tree?category=cnfutures_sector", headers=headers,
        )) as response:
            tree = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/product-library/tree", headers=headers,
        )) as response:
            uncategorized_tree = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/product-library/contracts?product=JNI.OSE",
            headers=headers,
        )) as response:
            contracts = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/market-data/prices",
            data=json.dumps({"product_name": "JNI.OSE"}).encode(),
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )) as response:
            prices = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/product-library/product-groups", headers=headers,
        )) as response:
            groups = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/product-library/product-groups",
            data=json.dumps({
                "name": "新建组", "paths": ["China Futures/Day"],
                "category_ids": ["cnfutures_sector"],
            }).encode(),
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )) as response:
            created = json.loads(response.read())

    assert sources["sources"] == [{"id": "Local", "source_kind": "server"}]
    assert tree["category_id"] == "cnfutures_sector"
    assert tree["tree"][0]["title"] == "cnfutures_sector"
    assert tree["tree"][0]["source_ids"] == tree["source_ids"]
    assert tree["tree"][0]["origin"] == "server"
    assert uncategorized_tree["category_id"] == ""
    assert uncategorized_tree["tree"][0]["title"] == "Product"
    assert contracts["product"] == "JNI.OSE"
    assert prices["product"] == "JNI.OSE"
    assert groups["groups"] == [{
        "name": "候选组", "principal": "user@1", "catalog_origin": "server",
    }]
    assert created["group"] == {
        "group_ref": "product-group:created",
        "name": "新建组",
        "paths": ["China Futures/Day"],
        "category_ids": ["cnfutures_sector"],
        "principal": "user@1",
    }


def test_product_group_summary_does_not_expand_catalog_memberships(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state.client_state,
        "product_group_summaries",
        lambda principal: [{
            "group_ref": "product-group:one",
            "name": "Group One",
            "path_count": 2944,
            "principal": principal,
        }],
    )
    monkeypatch.setattr(
        state.client_state,
        "product_groups",
        lambda _principal: pytest.fail(
            "summary list must not expand product-group memberships"
        ),
    )
    monkeypatch.setattr(
        state.gateway,
        "request",
        lambda **_values: pytest.fail(
            "summary list must not use a business service port"
        ),
    )

    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/product-library/product-groups?view=summary",
            headers={"Authorization": "Bearer user-token"},
        )) as response:
            value = json.loads(response.read())

    assert value["groups"] == [{
        "group_ref": "product-group:one",
        "name": "Group One",
        "path_count": 2944,
        "principal": "user@1",
    }]


def test_manager_product_catalog_passes_parallel_category_selection(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    calls = []

    def product_tree(category, source_ids, principal):
        calls.append((category, list(source_ids), principal))
        return [{"title": "日夜盘"}, {"title": "行业"}]

    monkeypatch.setattr(state.client_state, "product_tree", product_tree)
    headers = {"Authorization": "Bearer user-token"}
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/product-library/tree?category=cnfutures_day_night"
            "&category=cnfutures_sector",
            headers=headers,
        )) as response:
            value = json.loads(response.read())

    assert value["category_ids"] == ["cnfutures_day_night", "cnfutures_sector"]
    assert value["tree"] == [{"title": "日夜盘"}, {"title": "行业"}]
    assert calls[0][0] == ["cnfutures_day_night", "cnfutures_sector"]
    assert r"/api/internal/market-data/prices" not in _SERVICE_WRITE_PATTERNS["POST"]


def test_manager_product_catalog_can_request_selectable_tree_nodes(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    calls = []

    def product_tree(category, source_ids, principal, *, checkbox_default=False):
        calls.append((category, list(source_ids), principal, checkbox_default))
        return [{"title": "Product", "checkbox": checkbox_default}]

    monkeypatch.setattr(state.client_state, "product_tree", product_tree)
    headers = {"Authorization": "Bearer user-token"}
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/product-library/tree?checkbox=1", headers=headers,
        )) as response:
            value = json.loads(response.read())

    assert value["tree"] == [{"title": "Product", "checkbox": True}]
    assert calls == [("", ["Local"], "user@1", True)]


def test_server_catalog_has_no_client_local_projection_contract() -> None:
    from server.services.product_catalog_projection import (
        catalog_product_records,
        product_source_descriptors,
    )

    server_ids = {
        item["id"] for item in product_source_descriptors()
    }
    assert "Tiger" not in server_ids
    assert all(
        item["name"] != "JNI.OSE"
        for item in catalog_product_records()
    )
    assert "origin" not in inspect.signature(product_source_descriptors).parameters
    assert "origin" not in inspect.signature(catalog_product_records).parameters


def test_catalog_description_does_not_fallback_to_machine_identifier() -> None:
    from server.services.product_catalog_projection import catalog_product_description

    class Product:
        name = "A.DCE"
        alias = "A.DCE"
        code = "A"
        desc = ""

    product = Product()
    assert catalog_product_description(product, product.name) == ""
    product.desc = "黄大豆1号"
    assert catalog_product_description(product, product.name) == "黄大豆1号"


def test_catalog_exposes_only_base_category_dimensions() -> None:
    from server.modules.shared.price_services import available_product_categories

    categories = available_product_categories()
    assert {item["id"] for item in categories} == {
        "cnfutures_day_night", "cnfutures_sector",
    }


def test_product_tree_source_filter_prunes_unavailable_branches(monkeypatch) -> None:
    from server.services import product_catalog_projection as projection

    class Product:
        def __init__(self, name):
            self.name = name

    class Source:
        def supports_product(self, product):
            return product.name == "available"

    monkeypatch.setattr(
        projection,
        "_visible_source_index",
        lambda: {"Selected": Source()},
    )
    value = projection.filter_product_tree({
        "Root": {
            "Available": {"$OBJECTS$": [Product("available")]},
            "Unavailable": {"$OBJECTS$": [Product("missing")]},
        },
    }, ["Selected"])

    assert "Available" in value["Root"]
    assert "Unavailable" not in value["Root"]


def test_local_bundle_filters_real_product_tree_without_a_service_port() -> None:
    from server.manager.services.client_state import ClientStateService
    from server.services.product_catalog_projection import available_source_ids

    source_ids = available_source_ids()
    assert "Local" in source_ids
    tree = ClientStateService.product_tree(
        "cnfutures_day_night×cnfutures_sector", ("Local",),
    )

    assert tree
    assert tree[0]["title"] == "Product"
    assert tree[0]["key"] == "Product"
    nodes = list(_walk_product_nodes(tree))
    assert not any(
        node["key"].startswith("ProductCategory/") for node in nodes
    )
    assert any(
        "/ProductCategory/cnfutures_day_night×cnfutures_sector" in node["key"]
        for node in nodes
    )


def _walk_product_nodes(nodes):
    for node in nodes:
        yield node
        yield from _walk_product_nodes(node.get("children") or [])


def test_product_detail_renderer_is_loaded_as_a_separate_catalog_module(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/catalog/details.js") as response:
            details = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/catalog/products.js") as response:
            products = response.read().decode("utf-8")

    assert "window.FTProductDetails" in details
    assert "detailHelpers" in products
    assert "async function productDetail(context, target)" in products
    assert 'context.servicePath("/api/internal/market-data/prices")' not in details
    assert "FTProductPricePanel.render" in details
    assert "product-price-panel-mount" in details
    assert '"/api/market-data/prices"' not in details
    assert '"/api/product-library/contracts"' in details


@pytest.mark.parametrize(
    "path",
    [
        "/api/client/product_sources",
        "/api/client/product_names?data_source=Tiger",
        "/api/client/product_tree?data_source=Tiger",
        "/api/client/product-groups",
    ],
)
def test_client_local_catalog_is_not_served_by_manager(
    tmp_path,
    path: str,
) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        request = Request(
            f"{base_url}{path}",
            headers={"Authorization": "Bearer user-token"},
        )
        with pytest.raises(HTTPError) as captured:
            urlopen(request)
    assert captured.value.code == 404


def test_product_group_ui_explains_creator_research_and_unavailable_members(
    tmp_path,
) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/catalog/products.js") as response:
            products = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/catalog/details.js") as response:
            details = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/catalog/product-group-detail.js") as response:
            group_details = response.read().decode("utf-8")

    assert "creator_kind" in products
    assert "research_bindings" in products
    assert 'context.t("未绑定研究")' in products
    assert "unavailableProductDetail" in details
    assert "非服务器提供，无法展示相关信息" in details
    assert 'context.t("产品数量")' in group_details
    assert "FTCatalogDetailUI.header" in group_details


def test_product_tree_renderer_is_published_with_product_page(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/catalog/product-tree.js") as response:
            script = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/catalog/product-list-table.js") as response:
            table_script = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/catalog/product-categories.js") as response:
            categories = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/catalog/product-category-create.js") as response:
            create_script = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/catalog/product-category-detail.js") as response:
            detail_script = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/catalog/shared/selection-tree.js") as response:
            selection_tree = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/catalog/product-category-detail-layout.js") as response:
            detail_layout = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/catalog/product-category-label-editor.js") as response:
            label_editor = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/catalog/product-category-overlay.js") as response:
            overlay = response.read().decode("utf-8")
    assert "window.FTProductTree" in script
    assert 'typeof options.loadTree === "function"' in script
    assert "loadTreeWithTimeout" in script
    assert "options.onTreeLoaded?.(tree)" in script
    assert "requestAnimationFrame" in script
    assert "window.FTProductListTable" in table_script
    assert "paginationModel" in table_script
    assert "product-list-search" in table_script
    assert "contractTreePath" in table_script
    assert "source_family_ids" in table_script
    assert "item?.members" in table_script
    assert "product-list-selection" in table_script
    assert "options.onSelectionChange" in table_script
    assert 'context.t("产品路径")' in table_script
    assert "创建乘积分类" not in script
    assert "product-category-filter" in script
    assert "FTMultiSelectFilter.create" in script
    assert 'input.type = "checkbox"' in script
    assert "categorySelectionID" in script
    assert "categoryCountLabel" in script
    assert "showCategoryFilter" in script
    assert "leafOnly" in script
    assert "isLeafPathNode" in script
    assert 'select.addEventListener("change"' not in script
    assert "应用分类" in script
    assert "product-category-actions" not in script
    assert "产品 Category" not in script
    assert "应用 Category" not in script
    assert "创建乘积 Category" not in script
    assert "FTProductCategoryModel.multiply" not in script
    assert "FTProductCategoryOverlay.choose" not in script
    assert "FTProductCategoryModel.treeNodeInitiallyOpen" in script
    assert "window.FTProductCategories" in categories
    assert '"新增分类"' in categories
    assert '"新增乘积分类"' in categories
    assert "const showWriteActions = !context.session || source !== \"local\";" in categories
    assert "rejectVisitorOrLocalWrite" in categories
    assert "window.alert(message)" in categories
    assert "FTProductCategoryOverlay.choose" in categories
    assert 'context.t("分类 ID")' in categories
    assert 'context.t("来源/所有者")' in categories
    assert 'context.t("Label 数")' in categories
    assert 'context.t("父分类")' in categories
    assert 'context.t("路径数")' not in categories
    assert "FTProductCategoryCreate.open" not in categories
    assert "FTProductCategoryDetails.render" in create_script
    assert "显示产品树" in label_editor
    assert "隐藏产品树" in label_editor
    assert "loadSources" in detail_script
    assert "leafOnly: options.leafOnly !== false" in selection_tree
    assert "helpers.loadTree" in selection_tree
    assert "sourceIDs: []" in detail_script
    assert 'query.append("category", category.id)' not in detail_script
    assert "product-category-inline-tree" in label_editor
    detail_surface = detail_script + detail_layout + label_editor
    assert "selectionReadOnly" in selection_tree
    assert "从父分类更新内容" in detail_script
    assert "parent_category_ids" in detail_surface
    assert "DELETE" in detail_script
    assert "product-category-detail-layout" in detail_layout
    assert "product-category-inline-tree" in label_editor
    assert "mode === \"edit\"" in detail_layout
    assert "mode === \"view\"" not in detail_layout
    assert "ProductCategory/" in detail_surface
    assert "policy.label_remove" in detail_layout
    assert "removable: options.removable === true" in label_editor
    assert "/products/categories?updated=" in detail_script
    assert "window.FTProductCategoryOverlay" in overlay
    assert "创建乘积分类" in overlay
    assert "选择两个已有分类" in overlay
    assert "创建乘积 Category" not in overlay
    assert "选择两个已有 Category" not in overlay
    assert 'input.type = "checkbox"' in overlay
    assert "showModal" in overlay
    assert "day_night_x_sector" not in script


def test_job_port_metadata_includes_automatic_selection(tmp_path, monkeypatch) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(state, "service_ports", lambda: [8141, 8152])
    monkeypatch.setattr(state, "preferred_service_port", lambda: 8141)
    with running_manager(state) as base_url:
        request = Request(
            f"{base_url}/api/jobs/ports",
            headers={"Authorization": "Bearer user-token"},
        )
        with urlopen(request) as response:
            value = json.loads(response.read())

    assert value == {"ports": [8141, 8152], "automatic_port": 8141}


def test_report_snapshot_reference_reuses_reference_presentation_seam() -> None:
    root = ROOT / "server" / "manager" / "web"
    reference = (root / "research" / "reference.js").read_text(encoding="utf-8")
    report_entry = (root / "report" / "report-entry.js").read_text(encoding="utf-8")
    assert "headerFor" in reference
    assert "FTReferencePage?.headerFor" in report_entry
    assert "reference-tone-${presentation.tone}" in report_entry


def test_report_reader_switches_branches_inside_the_active_report_tab() -> None:
    report_entry = (
        ROOT / "server" / "manager" / "web" / "report" / "report-entry.js"
    ).read_text(encoding="utf-8")

    assert 'branch.publication_id || ""' in report_entry
    assert 'reportReadingByBranch[publicationID]' in report_entry
    assert 'context.updateActiveTab({path: target.href})' in report_entry
    assert 'render(targetPublicationID, context)' in report_entry
