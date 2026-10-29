from __future__ import annotations

import io
import json
import time
from unittest.mock import Mock

from server.identity.federation_identity_sync import (
    identity_sync_disable_signature,
)
from server.identity.realm_groups import (
    organization_admin_group_path,
    organization_group_path,
)
from server.manager.domain.federation import FederatedGateway, ServiceRoute
from server.manager.http.federation import admin as admin_routes
from server.manager.http.federation import sync as sync_routes
from server.manager.http.federation.admin import FederationAdminRoutesMixin
from server.manager.http.federation.sync import FederationSyncRoutesMixin
from server.manager.http.peer_handler import PeerControlHandler


class _Response(io.BytesIO):
    status = 200


class _Registry:
    def __init__(self, peer):
        self.peer = peer

    def describe(self, server_id):
        return dict(self.peer) if server_id == self.peer["server_id"] else None

    def servers(self, *, include_offline=True):
        del include_offline
        return [dict(self.peer)]


class _FakeKeycloak:
    def __init__(self, group_path):
        self.group_path = group_path
        self.updated = []

    def group_representations(self):
        return [{"id": "org", "path": self.group_path, "name": "Org"}]

    def update_group_attributes(self, group_path, attributes):
        self.updated.append((group_path, attributes))
        return {
            "id": "org",
            "path": group_path,
            "name": "Org",
            "attributes": attributes,
        }


class _InternalState:
    server_id = "internal-node-1"
    public_server = False
    managed_organizations = ("ResearchOrg",)

    def __init__(self, *, online=True, endpoint="http://10.20.0.1:17998"):
        self.endpoint = endpoint
        self.peer = {
            "server_id": "public-node-1",
            "role": "main",
            "public_server": True,
            "online": online,
            "proxy_token": "public-peer-token",
            "transfer_node": {"peer_control_endpoint": endpoint},
        }
        self.federation_registry = _Registry(self.peer)
        self.gateway_calls = []
        self.group_updates = []
        self.federation_gateway = self

    def federation_config(self):
        return {
            "bootstrap_url": self.endpoint + "/api/federation/register",
        }

    def federation_proxy_token(self):
        return "internal-peer-secret"

    def check_identity_sync_disable(self, route, **kwargs):
        self.gateway_calls.append((route, kwargs))
        return {"allowed": True, **kwargs}


class _InternalHandler(FederationAdminRoutesMixin):
    def __init__(self, state, payload):
        self.state = state
        self.payload = payload
        self.org_path = organization_group_path("ResearchOrg")
        self.keycloak = _FakeKeycloak(self.org_path)

    def _session(self):
        return {"keycloak_groups": [organization_admin_group_path("ResearchOrg")]}

    def _has_secure_ui_transport(self):
        return True

    def _has_super_admin_session(self):
        return False

    def _json_body(self, _limit):
        return self.payload


class _PublicHandler(FederationSyncRoutesMixin):
    def __init__(self, payload, *, peer_online=True, managed_orgs=("ResearchOrg",)):
        self.payload = payload
        self.peer = {
            "server_id": "internal-node-1",
            "public_server": False,
            "role": "feat",
            "online": peer_online,
            "proxy_token": "internal-peer-secret",
            "managed_organizations": list(managed_orgs),
        }
        self.state = type("PublicState", (), {
            "server_id": "public-node-1",
            "public_server": True,
            "federation_registry": _Registry(self.peer),
        })()

    def _has_federation_proxy_token(self):
        return True

    def _json_body(self, _limit):
        return self.payload


def _capture(monkeypatch, module):
    replies = []
    monkeypatch.setattr(
        module, "json_response",
        lambda _handler, payload, status=200, **_kwargs: replies.append((payload, status)),
    )
    return replies


def _valid_public_payload(*, group_path=None, requester="internal-node-1"):
    group_path = group_path or organization_group_path("ResearchOrg")
    issued_at = int(time.time())
    request_id = "0123456789abcdef0123456789abcdef"
    return {
        "requester_server_id": requester,
        "group_path": group_path,
        "issued_at": issued_at,
        "request_id": request_id,
        "signature": identity_sync_disable_signature(
            "internal-peer-secret",
            requester_server_id=requester,
            group_path=group_path,
            issued_at=issued_at,
            request_id=request_id,
        ),
    }


def test_internal_sync_disable_rejects_immediately_when_public_manager_is_offline(
    monkeypatch,
):
    replies = _capture(monkeypatch, admin_routes)
    state = _InternalState(online=False)
    handler = _InternalHandler(state, {
        "group_path": organization_group_path("ResearchOrg"),
        "enabled": False,
    })
    adapter_calls = []
    monkeypatch.setattr(
        admin_routes, "manager_keycloak_admin_adapter",
        lambda: adapter_calls.append("called") or handler.keycloak,
    )

    handler._update_admin_federation_settings()

    assert replies[-1][1] == 503
    assert replies[-1][0]["code"] == "identity_sync_verifier_unavailable"
    assert "offline" in replies[-1][0]["error"]
    assert state.gateway_calls == []
    assert adapter_calls == []
    assert handler.keycloak.updated == []


def test_internal_sync_disable_is_written_only_after_public_allow_decision(monkeypatch):
    replies = _capture(monkeypatch, admin_routes)
    state = _InternalState(online=True)
    handler = _InternalHandler(state, {
        "group_path": organization_group_path("ResearchOrg"),
        "enabled": False,
    })
    monkeypatch.setattr(
        admin_routes, "manager_keycloak_admin_adapter", lambda: handler.keycloak,
    )

    handler._update_admin_federation_settings()

    assert replies[-1][1] == 200
    assert state.gateway_calls[0][1] == {
        "requester_server_id": "internal-node-1",
        "requester_proxy_token": "internal-peer-secret",
        "group_path": organization_group_path("ResearchOrg"),
    }
    assert handler.keycloak.updated == [(
        organization_group_path("ResearchOrg"),
        {"tr_identity_sync_enabled": ["false"]},
    )]


def test_internal_sync_disable_keeps_policy_unchanged_when_public_denies(monkeypatch):
    replies = _capture(monkeypatch, admin_routes)
    state = _InternalState(online=True)

    def deny(_route, **kwargs):
        state.gateway_calls.append((_route, kwargs))
        return {"allowed": False}

    state.check_identity_sync_disable = deny
    handler = _InternalHandler(state, {
        "group_path": organization_group_path("ResearchOrg"),
        "enabled": False,
    })
    monkeypatch.setattr(
        admin_routes, "manager_keycloak_admin_adapter", lambda: handler.keycloak,
    )

    handler._update_admin_federation_settings()

    assert replies[-1][1] == 409
    assert replies[-1][0]["code"] == "identity_sync_admin_handoff_required"
    assert handler.keycloak.updated == []


def test_internal_sync_disable_fails_closed_on_verifier_timeout(monkeypatch):
    replies = _capture(monkeypatch, admin_routes)
    state = _InternalState(online=True)

    def timeout(_route, **_kwargs):
        raise ConnectionError("timeout")

    state.check_identity_sync_disable = timeout
    handler = _InternalHandler(state, {
        "group_path": organization_group_path("ResearchOrg"),
        "enabled": False,
    })
    monkeypatch.setattr(
        admin_routes, "manager_keycloak_admin_adapter", lambda: handler.keycloak,
    )

    handler._update_admin_federation_settings()

    assert replies[-1][1] == 503
    assert replies[-1][0]["code"] == "identity_sync_verifier_unavailable"
    assert handler.keycloak.updated == []


def test_public_manager_binds_one_time_decision_to_registered_internal_scope(
    monkeypatch,
):
    replies = _capture(monkeypatch, sync_routes)
    handler = _PublicHandler(_valid_public_payload())
    checker_calls = []

    class PublicKeycloak:
        def client_role_users(self, *_args, **_kwargs):
            return [{"id": "other-admin", "username": "private", "enabled": True}]

        def user_group_paths(self, user_id, **_kwargs):
            return {organization_group_path("OperationsOrg") + "/levels/root"}

    monkeypatch.setattr(
        sync_routes, "manager_keycloak_admin_adapter",
        lambda: checker_calls.append("keycloak") or PublicKeycloak(),
    )
    monkeypatch.setattr(
        "server.identity.user_session.oidc_settings",
        lambda: {"roles_client_id": "manager-api"},
    )

    handler._federation_identity_sync_check_disable()

    assert replies[-1][1] == 200
    assert replies[-1][0]["success"] is True
    assert replies[-1][0]["allowed"] is True
    assert replies[-1][0]["request_id"] == handler.payload["request_id"]
    assert checker_calls == ["keycloak"]


def test_public_manager_denial_is_a_bound_decision_without_role_mutation(monkeypatch):
    replies = _capture(monkeypatch, sync_routes)
    handler = _PublicHandler(_valid_public_payload())

    class PublicKeycloak:
        def client_role_users(self, *_args, **_kwargs):
            return [{"id": "same-org-admin", "username": "private", "enabled": True}]

        def user_group_paths(self, user_id, **_kwargs):
            return {organization_group_path("ResearchOrg") + "/levels/root"}

    monkeypatch.setattr(
        sync_routes, "manager_keycloak_admin_adapter", lambda: PublicKeycloak(),
    )
    monkeypatch.setattr(
        "server.identity.user_session.oidc_settings",
        lambda: {"roles_client_id": "manager-api"},
    )

    handler._federation_identity_sync_check_disable()

    assert replies[-1][1] == 200
    assert replies[-1][0]["allowed"] is False
    assert replies[-1][0]["group_path"] == organization_group_path("ResearchOrg")


def test_public_manager_rejects_wrong_org_or_offline_requesting_peer(monkeypatch):
    replies = _capture(monkeypatch, sync_routes)
    handler = _PublicHandler(_valid_public_payload(), managed_orgs=("OtherOrg",))

    handler._federation_identity_sync_check_disable()
    assert replies[-1][1] == 403

    handler = _PublicHandler(_valid_public_payload(), peer_online=False)
    handler._federation_identity_sync_check_disable()
    assert replies[-1][1] == 409


def test_gateway_sends_peer_proof_without_sending_peer_secret():
    captured = {}

    class Transport:
        def open(self, request, *, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            sent = json.loads(request.data.decode("utf-8"))
            captured["body"] = sent
            captured["timeout"] = timeout
            response = {
                "success": True,
                "allowed": True,
                "requester_server_id": sent["requester_server_id"],
                "group_path": sent["group_path"],
                "request_id": sent["request_id"],
            }
            return _Response(json.dumps(response).encode("utf-8"))

    gateway = FederatedGateway(timeout=10.0, transport=Transport())
    route = ServiceRoute(
        server_id="public-node-1", role="main", branch="main", revision="abc",
        port=0, peer_control_endpoint="http://10.20.0.1:17998",
        proxy_token="public-peer-token", remote=True, online=True, public_server=True,
    )
    result = gateway.check_identity_sync_disable(
        route,
        requester_server_id="internal-node-1",
        requester_proxy_token="internal-peer-secret",
        group_path=organization_group_path("ResearchOrg"),
    )

    assert result["allowed"] is True
    assert captured["url"].endswith("/api/federation/identity-sync/check-disable")
    assert captured["timeout"] == 5.0
    assert captured["headers"]["Authorization"] == "Bearer public-peer-token"
    assert "internal-peer-secret" not in json.dumps(captured["body"])
    body = captured["body"]
    assert body["signature"] == identity_sync_disable_signature(
        "internal-peer-secret",
        requester_server_id=body["requester_server_id"],
        group_path=body["group_path"],
        issued_at=body["issued_at"],
        request_id=body["request_id"],
    )


def test_private_peer_control_dispatches_sync_disable_verification_route():
    handler = Mock()
    handler.path = "/api/federation/identity-sync/check-disable"

    PeerControlHandler.do_POST(handler)

    handler._federation_identity_sync_check_disable.assert_called_once_with()
