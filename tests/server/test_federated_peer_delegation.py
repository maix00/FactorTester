from types import SimpleNamespace

import pytest

from server.identity import federated_peer_delegation as module
from server.identity.keycloak_authorization import AuthorizationUnavailable


def fixture(monkeypatch):
    fingerprint = "a" * 64
    endpoint = "http://10.0.0.3:17998"
    attrs = {
        "tr_internal_manager_id": ["peer"], "tr_node_key_fingerprint": [fingerprint],
        "tr_federation_oidc_issuer": ["https://peer.example/realms/org"],
        "tr_federation_exchange_client_id": ["delegate-source"],
        "tr_federation_introspection_client_id": ["introspect-peer"],
        "tr_federation_authz_client_id": ["source-resources"],
        "tr_federation_authz_resource_id": ["source-permission"],
        "tr_federation_incoming_authz_resource_id": ["target-permission"],
    }
    class Adapter:
        def _get(self, path):
            return {"path": "/" + path.split("group-by-path/", 1)[1], "attributes": attrs}
    from server.identity import federation_identity_sync
    monkeypatch.setattr(federation_identity_sync, "manager_keycloak_admin_adapter", lambda: Adapter())
    node = SimpleNamespace(node_id="peer", fingerprint=fingerprint)
    lease = SimpleNamespace(online=True, peer_control_endpoint=endpoint)
    row = {"transfer_node": {"node_id": "peer", "identity": {"fingerprint": fingerprint},
                             "peer_control_endpoint": endpoint}}
    state = SimpleNamespace(server_id="local", node_identities=SimpleNamespace(require=lambda _: node),
        transfer_endpoints=SimpleNamespace(require=lambda _: lease),
        federation_registry=SimpleNamespace(describe=lambda _: row))
    return state, attrs, node, lease, row


def test_binding_uses_existing_signed_node_and_exact_keycloak_group(monkeypatch):
    state, attrs, node, lease, row = fixture(monkeypatch)
    value = module.bound_peer(state, "peer", expected_endpoint="http://10.0.0.3:17998")
    assert value.issuer == "https://peer.example/realms/org"
    assert value.authorization_resource == "source-permission"
    with pytest.raises(PermissionError):
        module.bound_peer(state, "peer", expected_endpoint="http://10.0.0.4:17998")
    attrs["tr_node_key_fingerprint"] = ["b" * 64]
    with pytest.raises(PermissionError):
        module.bound_peer(state, "peer")
    attrs["tr_node_key_fingerprint"] = [node.fingerprint]
    lease.online = False
    with pytest.raises(PermissionError):
        module.bound_peer(state, "peer")
    lease.online = True
    row["transfer_node"]["identity"]["fingerprint"] = "c" * 64
    with pytest.raises(PermissionError):
        module.bound_peer(state, "peer")


@pytest.mark.parametrize("change", [
    {"tr_federation_oidc_issuer": ["http://public.example/realms/org"]},
    {"tr_federation_oidc_issuer": ["https://peer.example/realms/org/extra"]},
    {"tr_federation_authz_resource_id": ["one", "two"]},
    {"tr_federation_incoming_authz_resource_id": []},
])
def test_missing_or_ambiguous_peer_keycloak_configuration_is_not_trusted(monkeypatch, change):
    state, attrs, *_ = fixture(monkeypatch)
    attrs.update(change)
    with pytest.raises(AuthorizationUnavailable):
        module.bound_peer(state, "peer")


def test_exchange_requires_live_local_identity_before_calling_keycloak(monkeypatch):
    state, *_ = fixture(monkeypatch)
    binding = module.bound_peer(state, "peer")
    identity = {"username": "alice", "tr_identity_id": "stable-1"}
    state.session = lambda _token: identity
    calls = []
    client = SimpleNamespace(exchange_token=lambda token, **kwargs: calls.append((token, kwargs)) or
                             {"access_token": "assertion"})
    monkeypatch.setattr(module, "oidc_settings", lambda: {})
    monkeypatch.setattr(module, "_local_client", lambda _: client)
    monkeypatch.setattr(module, "server_admission", lambda *_a, **_k: (False, "denied"))
    with pytest.raises(PermissionError):
        module.exchange_for_peer(state, binding, token="token", principal="alice")
    assert calls == []
    monkeypatch.setattr(module, "server_admission", lambda *_a, **kwargs: (kwargs["use_cache"] is False, ""))
    with pytest.raises(PermissionError):
        module.exchange_for_peer(state, binding, token="token", principal="someone-else")
    assert module.exchange_for_peer(state, binding, token="token", principal="alice") == ("assertion", "stable-1")
    assert calls == [("token", {"audience": binding.issuer, "scope": ""})]
