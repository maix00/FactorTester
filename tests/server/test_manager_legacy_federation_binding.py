from __future__ import annotations

import sqlite3
import time
from types import SimpleNamespace

import pytest

from server.identity import server_admission
from server.manager.domain.federation.registry import FederatedServerRegistry
from server.manager.http.federation import admin as admin_module
from server.manager.http.federation.admin import FederationAdminRoutesMixin
from server.manager.transfers.node_advertisements import signed_advertisement
from server.manager.transfers.node_keys import NodeKey
from tests.federation_fixtures import federation_registration


@pytest.fixture
def case(tmp_path, monkeypatch):
    import settings
    monkeypatch.setattr(settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    registry = FederatedServerRegistry(tmp_path / "registry.json")
    key = NodeKey.load_or_create(tmp_path / "node-key.json", node_id="node-a")
    advertisement = signed_advertisement({
        "schema_version": 2, "node_id": "node-a", "identity": key.public_record(),
        "client_control_endpoint": "https://node-a.example:7998",
        "client_data_endpoint": "https://node-a.example:7997",
        "peer_control_endpoint": "https://node-a.example:17998",
        "peer_data_endpoint": "https://node-a.example:17997",
        "issued_at": time.time() - 3600, "lease_seconds": 30.0,
        "nonce": "0123456789abcdef",
    }, node_key=key)
    row = federation_registration("node-a", latency_ms=1, load=0)
    row.update(role="feat", public_server=False, managed_organizations=[],
               transfer_node=advertisement)
    registry.register(row)
    fingerprint = key.fingerprint
    node = SimpleNamespace(public_key=key.public_key, fingerprint=fingerprint)
    state = SimpleNamespace(public_server=True, federation_registry=registry,
                            node_identities=SimpleNamespace(require=lambda _: node))
    replies = []
    monkeypatch.setattr(admin_module, "json_response",
                        lambda _, value, status=200, **kw: replies.append((status, value)))
    monkeypatch.setattr(server_admission, "current_manager_role", lambda *_: True)
    monkeypatch.setattr(server_admission, "federated_manager_binding", lambda *_, **__: True)

    class Handler(FederationAdminRoutesMixin):
        def __init__(self):
            self.state = state
            self.payload = {"server_id": "node-a", "organization_id": "org-a",
                            "fingerprint": fingerprint}
        def _session(self):
            return {"username": "admin", "keycloak_subject": "subject",
                    "keycloak_issuer": "https://id.example/realms/test",
                    "keycloak_roles": ["admin_console:manage"]}
        def _has_secure_ui_transport(self):
            return True
        def _json_body(self, _):
            return self.payload

    return Handler(), replies, tmp_path / "jobs.sqlite"


def test_unverified_or_tampered_historical_advertisement_cannot_bind(case):
    handler, replies, db = case
    # Even an expired advertisement is valid proof of the enrolled identity,
    # but editing the saved signed data must invalidate that proof.
    row = handler.state.federation_registry._servers["node-a"]
    row["transfer_node"]["client_data_endpoint"] = "https://other.example:7997"
    handler._bind_legacy_internal_manager()
    assert replies[-1][0] == 403
    assert not db.exists()
    assert handler.state.federation_registry.describe("node-a")["managed_organizations"] == []


def test_explicit_binding_requires_live_super_admin_and_keycloak_node_binding(case, monkeypatch):
    handler, replies, db = case
    monkeypatch.setattr(server_admission, "current_manager_role", lambda *_: False)
    handler._bind_legacy_internal_manager()
    assert replies[-1][0] == 403
    assert not db.exists()
    monkeypatch.setattr(server_admission, "current_manager_role", lambda *_: True)
    monkeypatch.setattr(server_admission, "federated_manager_binding", lambda *_, **__: False)
    handler._bind_legacy_internal_manager()
    assert replies[-1][0] == 403
    assert handler.state.federation_registry.describe("node-a")["managed_organizations"] == []


def test_explicit_binding_dry_run_apply_and_retry_are_audited_once(case):
    handler, replies, db = case
    handler._bind_legacy_internal_manager()
    assert replies[-1][0] == 200
    assert replies[-1][1]["dry_run"] is True
    assert not db.exists()
    reviewed = replies[-1][1]["plan"]["record_sha256"]
    handler.payload.update(dry_run=False, expected_sha256=reviewed)
    handler._bind_legacy_internal_manager()
    assert replies[-1][1]["binding"]["status"] == "bound"
    assert handler.state.federation_registry.describe("node-a")["managed_organizations"] == ["org-a"]
    handler._bind_legacy_internal_manager()
    assert replies[-1][1]["binding"]["status"] == "already_bound"
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT action, detail FROM job_dispatch_audit ORDER BY id").fetchall()
    assert [row[0] for row in rows] == ["manager-organization-bind-intent", "manager-organization-bind-applied"]
    assert all("proxy-node-a" not in row[1] for row in rows)


def test_interrupted_completion_audit_is_repaired_by_exact_retry(case, monkeypatch):
    import server.jobs.dispatch.audit as audit
    handler, replies, db = case
    handler._bind_legacy_internal_manager()
    reviewed = replies[-1][1]["plan"]["record_sha256"]
    handler.payload.update(dry_run=False, expected_sha256=reviewed)
    real_append = audit.append_audit
    failed = False
    def interrupted(*args, **kwargs):
        nonlocal failed
        if kwargs["action"].endswith("-applied") and not failed:
            failed = True
            raise OSError("simulated audit interruption")
        return real_append(*args, **kwargs)
    monkeypatch.setattr(audit, "append_audit", interrupted)
    handler._bind_legacy_internal_manager()
    assert replies[-1][0] == 503
    assert handler.state.federation_registry.describe("node-a")["managed_organizations"] == ["org-a"]
    handler._bind_legacy_internal_manager()
    assert replies[-1][0] == 200
    with sqlite3.connect(db) as conn:
        actions = [row[0] for row in conn.execute("SELECT action FROM job_dispatch_audit ORDER BY id")]
    assert actions == ["manager-organization-bind-intent", "manager-organization-bind-applied"]


def test_changed_keycloak_binding_before_write_does_not_mutate(case, monkeypatch):
    handler, replies, db = case
    handler._bind_legacy_internal_manager()
    reviewed = replies[-1][1]["plan"]["record_sha256"]
    handler.payload.update(dry_run=False, expected_sha256=reviewed)
    calls = 0
    def check(*_, **__):
        nonlocal calls
        calls += 1
        return calls == 1
    monkeypatch.setattr(server_admission, "federated_manager_binding", check)
    handler._bind_legacy_internal_manager()
    assert replies[-1][0] == 403
    assert not db.exists()
    assert handler.state.federation_registry.describe("node-a")["managed_organizations"] == []
