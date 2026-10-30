from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from server.manager import runtime as manager
from server.manager.http.federation import jobs
from server.manager.http.peer_handler import peer_control_handler
from server.manager.transfers.node_client import NodeControlClient
from server.manager.transfers.node_keys import NodeKey


def test_signed_job_query_uses_target_realm_identity_and_never_stale_rows(tmp_path, monkeypatch):
    state = manager.ManagerState(tmp_path / "repo", "python", server_role="main",
        server_id="target", state_root=tmp_path / "state")
    source_key = NodeKey.load_or_create(tmp_path / "source.key", node_id="source")
    state.node_identities.enroll(source_key.public_record())
    calls = []
    monkeypatch.setattr(state, "aggregate_account_jobs", lambda **kwargs:
        calls.append(kwargs) or {"jobs": [{"job_id": "target-job"}], "total": 1})
    monkeypatch.setattr(jobs, "bound_peer", lambda _state, node_id: node_id)
    allow = {"value": True}
    def accept(_state, binding, *, assertion, stable_id, target_scope):
        assert binding == "source" and assertion == "source-assertion"
        assert stable_id == "stable-user" and target_scope == "read"
        if not allow["value"]:
            raise PermissionError("revoked")
        return SimpleNamespace(target_session={"username": "different-local-name",
            "tr_identity_id": stable_id}, target_token="target-realm-token")
    monkeypatch.setattr(jobs, "accept_from_peer", accept)
    server = ThreadingHTTPServer(("127.0.0.1", 0), peer_control_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = NodeControlClient(f"http://127.0.0.1:{server.server_address[1]}", key=source_key)
    payload = {"requester_server_id": "source", "identity_id": "stable-user",
               "delegation_assertion": "source-assertion", "scope": "mine", "page": 1, "limit": 20,
               "principal": "attacker-controlled"}
    try:
        result = client.signed_json("/api/federation/jobs/query", payload)
        assert result["jobs"][0]["job_id"] == "target-job"
        assert calls == [{"principal": "different-local-name", "scope": "mine", "page": 1, "limit": 20,
                          "delegated_user_token": "target-realm-token", "_allow_federation": False,
                          "_allow_stale": False}]
        allow["value"] = False
        with pytest.raises(HTTPError) as denied:
            client.signed_json("/api/federation/jobs/query", payload)
        assert denied.value.code == 403 and len(calls) == 1
        payload["requester_server_id"] = "forged-node"
        with pytest.raises(HTTPError) as forged:
            client.signed_json("/api/federation/jobs/query", payload)
        assert forged.value.code == 403 and len(calls) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_delegated_job_query_does_not_fall_back_to_cached_private_jobs(tmp_path, monkeypatch):
    state = manager.ManagerState(tmp_path / "repo", "python", server_role="main",
        server_id="target", state_root=tmp_path / "state")
    state.job_index.upsert("owner", [{"job_id": "stale", "port": 8000}])
    monkeypatch.setattr(state, "ordered_job_service_ports", lambda: [])
    with pytest.raises(ConnectionError):
        state.aggregate_account_jobs(principal="owner", scope="visible", delegated_user_token="local-token",
                                     _allow_federation=False, _allow_stale=False)
    with pytest.raises(ConnectionError):
        state.aggregate_server_jobs(principal="admin", delegated_user_token="local-token",
                                    _allow_federation=False, _allow_stale=False)


def test_subordinate_mapping_rechecks_current_keycloak_groups(monkeypatch):
    from server.identity import federation_identity_sync
    from server.identity.realm_groups import organization_group_path, organization_admin_group_path

    groups = {"admin-subject": [organization_admin_group_path("org")],
              "target-subject": [organization_group_path("org") + "/levels/a"]}
    class Adapter:
        def user_by_identity_id(self, stable):
            return {"id": "target-subject", "enabled": True, "username": "local-target",
                    "attributes": {"tr_identity_id": [stable], "legacy_username": ["local-label"]}}
        def user_group_paths(self, subject):
            return groups[subject]
    monkeypatch.setattr(federation_identity_sync, "manager_keycloak_admin_adapter", lambda: Adapter())
    monkeypatch.setattr(jobs, "current_manager_role", lambda *_: False)
    identity = {"tr_identity_id": "admin-id", "keycloak_subject": "admin-subject",
                # A stale token still contains this role; the live groups win.
                "keycloak_groups": [organization_admin_group_path("org")]}
    assert jobs._subordinate_username(identity, "target-id") == "local-label"
    groups["admin-subject"] = []
    with pytest.raises(PermissionError, match="current Keycloak hierarchy"):
        jobs._subordinate_username(identity, "target-id")
    groups["admin-subject"] = [organization_admin_group_path("other-org")]
    with pytest.raises(PermissionError, match="current Keycloak hierarchy"):
        jobs._subordinate_username(identity, "target-id")
