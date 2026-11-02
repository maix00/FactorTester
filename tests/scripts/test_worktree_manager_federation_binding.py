from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest

from server.manager.domain.federation.registry import (
    FederationRegistrationConflict,
    FederatedServerRegistry,
)
from tests.federation_fixtures import federation_registration


def registration(server_id, organization="org-a"):
    value = federation_registration(server_id, latency_ms=1, load=0)
    value.update(role="feat", public_server=False, managed_organizations=[organization])
    return value


@pytest.mark.parametrize("missing", [True, False])
def test_remote_missing_organization_never_inherits_local_environment(tmp_path, monkeypatch, missing):
    monkeypatch.setenv("FACTORTESTER_MANAGED_ORGANIZATIONS", "local-org")
    value = registration("node-a")
    if missing:
        value.pop("managed_organizations")
    else:
        value["managed_organizations"] = None
    registry = FederatedServerRegistry(tmp_path / "registry.json")
    assert registry.validate(value)["managed_organizations"] == []
    with pytest.raises(FederationRegistrationConflict, match="one_organization"):
        registry.register(value, enforce_single_organization=True)


def test_offline_binding_is_not_released_or_reassigned(tmp_path):
    registry = FederatedServerRegistry(tmp_path / "registry.json", lease_seconds=5)
    registry.register(registration("node-a"), enforce_single_organization=True)
    registry._servers["node-a"]["last_seen"] = 1
    effects = []
    with pytest.raises(FederationRegistrationConflict, match="already_registered"):
        registry.register(registration("node-b"), enforce_single_organization=True,
                          before_commit=lambda: effects.append("installed"))
    assert not effects
    assert registry.describe("node-b") is None
    # The same Manager may heartbeat after an offline interval.
    registry.register(registration("node-a"), enforce_single_organization=True)
    assert registry.servers(include_offline=False)[0]["server_id"] == "node-a"


def test_unbound_legacy_record_is_read_only_and_never_claimed(tmp_path):
    registry = FederatedServerRegistry(tmp_path / "registry.json")
    legacy = registration("node-a")
    legacy["managed_organizations"] = []
    registry.register(legacy)
    for node in ("node-a", "node-b"):
        with pytest.raises(FederationRegistrationConflict, match="needs_review"):
            registry.register(registration(node), enforce_single_organization=True)
    assert registry.describe("node-a")["managed_organizations"] == []
    assert registry.describe("node-b") is None


def test_explicit_legacy_binding_preserves_credentials_and_is_audited(tmp_path):
    registry = FederatedServerRegistry(tmp_path / "registry.json")
    value = registration("node-a")
    value["managed_organizations"] = []
    registry.register(value)
    before = registry.describe("node-a")
    plan = registry.legacy_binding_plan("node-a", "org-a")
    events = []
    result = registry.bind_reviewed_legacy(
        "node-a", "org-a", expected_sha256=plan["record_sha256"],
        verify=lambda: True, audit=lambda phase, row: events.append((phase, row["status"])),
    )
    assert result["status"] == "bound"
    assert events == [("intent", "reviewed_unbound"), ("applied", "bound")]
    after = registry.describe("node-a")
    assert {k: v for k, v in after.items() if k != "managed_organizations"} == {
        k: v for k, v in before.items() if k != "managed_organizations"
    }
    same = registry.legacy_binding_plan("node-a", "org-a")
    retry_events = []
    assert registry.bind_reviewed_legacy(
        "node-a", "org-a", expected_sha256=same["record_sha256"],
        verify=lambda: True, audit=lambda phase, _: retry_events.append(phase),
    )["status"] == "already_bound"
    assert registry.bind_reviewed_legacy(
        "node-a", "org-a", expected_sha256=plan["record_sha256"],
        verify=lambda: True, audit=lambda phase, _: retry_events.append(phase),
    )["status"] == "already_bound"
    assert retry_events == ["intent", "applied", "intent", "applied"]


def test_explicit_binding_rejects_drift_or_failed_identity_and_audit(tmp_path):
    registry = FederatedServerRegistry(tmp_path / "registry.json")
    value = registration("node-a")
    value["managed_organizations"] = []
    registry.register(value)
    plan = registry.legacy_binding_plan("node-a", "org-a")
    with pytest.raises(FederationRegistrationConflict, match="record_changed"):
        registry.bind_reviewed_legacy("node-a", "org-a", expected_sha256="bad",
                                      verify=lambda: True, audit=lambda *_: None)
    with pytest.raises(PermissionError):
        registry.bind_reviewed_legacy("node-a", "org-a", expected_sha256=plan["record_sha256"],
                                      verify=lambda: False, audit=lambda *_: None)
    def fail_audit(*_):
        raise OSError("audit unavailable")
    with pytest.raises(OSError, match="audit unavailable"):
        registry.bind_reviewed_legacy("node-a", "org-a", expected_sha256=plan["record_sha256"],
                                      verify=lambda: True, audit=fail_audit)
    assert registry.describe("node-a")["managed_organizations"] == []


def test_existing_manager_cannot_change_organization_via_heartbeat(tmp_path):
    registry = FederatedServerRegistry(tmp_path / "registry.json")
    registry.register(registration("node-a"), enforce_single_organization=True)
    with pytest.raises(FederationRegistrationConflict, match="organization_changed"):
        registry.register(registration("node-a", "org-b"), enforce_single_organization=True)
    assert registry.describe("node-a")["managed_organizations"] == ["org-a"]


def test_two_simultaneous_claims_cannot_both_register(tmp_path):
    registry = FederatedServerRegistry(tmp_path / "registry.json")
    barrier = threading.Barrier(2)
    effects = []

    def attempt(node):
        barrier.wait()
        try:
            registry.register(registration(node), enforce_single_organization=True,
                              before_commit=lambda: effects.append(node))
            return True
        except FederationRegistrationConflict:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ("node-a", "node-b")))
    assert sorted(results) == [False, True]
    assert len(effects) == 1
    assert len(registry.servers()) == 1


@pytest.mark.parametrize("content", ["{broken", json.dumps({"schema_version": 1, "servers": {"x": None}})])
def test_corrupt_registry_cannot_be_interpreted_as_unclaimed(tmp_path, content):
    path = tmp_path / "registry.json"
    path.write_text(content)
    registry = FederatedServerRegistry(path)
    with pytest.raises(FederationRegistrationConflict, match="needs_repair"):
        registry.register(registration("node-a"), enforce_single_organization=True)
    assert path.read_text() == content


def test_public_flag_must_be_a_real_boolean(tmp_path):
    registry = FederatedServerRegistry(tmp_path / "registry.json")
    value = registration("node-a")
    value["public_server"] = "false"
    with pytest.raises(ValueError, match="boolean"):
        registry.register(value, enforce_single_organization=True)


def test_signed_first_registration_requires_keycloak_organization_and_key(tmp_path, monkeypatch):
    from tests.scripts.test_worktree_manager_federation_routing import _federated_state
    from server.identity import server_admission

    receiver = _federated_state(tmp_path, "public", 10)
    receiver.public_server = True
    source = _federated_state(tmp_path, "node-a", 11)
    source.managed_organizations = ("org-a",)
    expected = source.node_key.fingerprint
    monkeypatch.setattr(server_admission, "federated_manager_binding",
                        lambda server, org, key: (server, org, key) == ("node-a", "org-a", expected))
    payload = source.registration_payload("https://node-a.example:7998")
    assert receiver.accept_federation_registration(payload)["server_id"] == "node-a"
    assert receiver.node_identities.require("node-a").fingerprint == expected


def test_first_registration_cannot_impersonate_a_bound_server(tmp_path, monkeypatch):
    from tests.scripts.test_worktree_manager_federation_routing import _federated_state
    from server.identity import server_admission

    receiver = _federated_state(tmp_path, "public", 10)
    receiver.public_server = True
    source = _federated_state(tmp_path, "node-a", 11)
    source.managed_organizations = ("org-a",)
    attacker_root = tmp_path / "attacker"
    attacker_root.mkdir()
    attacker = _federated_state(attacker_root, "node-a", 12)
    attacker.managed_organizations = ("org-a",)
    expected = source.node_key.fingerprint
    monkeypatch.setattr(server_admission, "federated_manager_binding",
                        lambda server, org, key: (server, org, key) == ("node-a", "org-a", expected))
    payload = attacker.registration_payload("https://node-a.example:7998")
    with pytest.raises(PermissionError, match="Keycloak denied"):
        receiver.accept_federation_registration(payload)
    assert receiver.federation_registry.describe("node-a") is None
    with pytest.raises(KeyError):
        receiver.node_identities.require("node-a")


def test_self_signed_advertisement_cannot_lie_about_its_fingerprint(tmp_path):
    from tests.scripts.test_worktree_manager_federation_routing import _federated_state
    from server.manager.transfers.node_advertisements import _canonical_payload

    source = _federated_state(tmp_path, "node-a", 11)
    payload = source.transfer_node_advertisement()
    payload["identity"]["fingerprint"] = "a" * 64
    # Simulate an attacker signing a false fingerprint with its own key.
    payload["signature"] = source.node_key.sign_bytes(_canonical_payload(payload))
    receiver = _federated_state(tmp_path, "receiver", 12)
    with pytest.raises(PermissionError, match="signature"):
        receiver.accept_transfer_node_advertisement(payload)
    with pytest.raises(KeyError):
        receiver.node_identities.require("node-a")


def test_fingerprint_rotation_requires_both_explicit_key_and_keycloak_changes(tmp_path, monkeypatch):
    from tests.scripts.test_worktree_manager_federation_routing import _federated_state
    from server.identity import server_admission

    receiver = _federated_state(tmp_path, "public", 10)
    receiver.public_server = True
    old = _federated_state(tmp_path, "node-a", 11)
    old.managed_organizations = ("org-a",)
    allowed = {old.node_key.fingerprint}
    monkeypatch.setattr(server_admission, "federated_manager_binding",
                        lambda server, org, key: server == "node-a" and org == "org-a" and key in allowed)
    receiver.accept_federation_registration(old.registration_payload("https://node-a.example:7998"))
    new_root = tmp_path / "rotated"
    new_root.mkdir()
    new = _federated_state(new_root, "node-a", 12)
    new.managed_organizations = ("org-a",)
    allowed.clear()
    allowed.add(new.node_key.fingerprint)
    with pytest.raises(ValueError, match="explicit rotation"):
        receiver.accept_federation_registration(new.registration_payload("https://node-a.example:7998"))
    receiver.node_identities.rotate(node_id="node-a", expected_fingerprint=old.node_key.fingerprint,
                                    public_key=new.node_key.public_key)
    assert receiver.accept_federation_registration(
        new.registration_payload("https://node-a.example:7998")
    )["server_id"] == "node-a"
    with pytest.raises(ValueError, match="explicit rotation"):
        receiver.accept_federation_registration(old.registration_payload("https://node-a.example:7998"))
