"""Federated public research, Profile, and factor projections."""

from __future__ import annotations

import time

from server.manager.domain.federation import ServiceRoute
import server.manager.http.federation.public_data as public_data_routes
from server.manager.http.federation.public_data import FederationPublicDataRoutesMixin
from server.manager.services.client_state import ClientStateService
from server.manager.services.federated_public_data import (
    FederatedPublicDataService,
)


def _route(server_id: str = "internal-1") -> ServiceRoute:
    return ServiceRoute(
        server_id=server_id,
        role="feat",
        branch="feat",
        revision="r1",
        port=7999,
        endpoint="http://10.0.0.8:7998",
        peer_control_endpoint="http://10.0.0.8:17998",
        proxy_token="proxy-token",
        remote=True,
        online=True,
        public_server=False,
    )


class _Registry:
    def __init__(self, route: ServiceRoute) -> None:
        self.route = route

    def routes(self, *, include_offline: bool) -> list[ServiceRoute]:
        return [self.route] if include_offline or self.route.online else []


class _Gateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.payloads: list[dict[str, object]] = []

    def public_data(self, route, *, kind, operation, principal, payload=None):
        self.calls.append((kind, operation, principal))
        self.payloads.append(dict(payload or {}))
        if kind == "research":
            if operation != "list":
                return {"value": {
                    "publication_id": payload["publication_id"],
                }}
            return {"reports": [{
                "publication_id": "remote-publication",
                "report_id": "remote-report",
                "title": "Remote report",
                "updated_at": 3,
            }]}
        if operation == "profiles":
            return {"profiles": [{
                "profile_id": "maxa",
                "display_name": "MaxA",
                "research_records": [{"record_id": "retired-graph-history"}],
            }]}
        if operation == "factors":
            return {"factors": [{
                "factor_ref": "factor:remote",
                "factor_alias": "RemoteMomentum",
                "factor_family_alias": "MomentumFamily",
                "factor_family_name": "MomentumFamily",
                "owner_username": "__public_jobs__",
                "owner_alias": "公共因子库",
                "factor_kind": "public",
                "params": [],
            }]}
        raise AssertionError(operation)


class _Research:
    def list_visible(self, _viewer):
        return []

    def index(self, _publication_id, _viewer):
        raise ValueError("publication is not local")


class _ClientState:
    def profiles(self, _principal, *, include_local_paths):
        assert include_local_paths is False
        return []

    def factor_library(self, principal):
        return {"principal": principal, "factors": [], "errors": []}

    def factor_library_scopes(self, principal):
        return {
            "mine": {
                "factors": [{
                    "factor_ref": "factor:mine",
                    "factor_alias": "MineFactor",
                    "factor_family_alias": "MineFamily",
                    "factor_family_name": "MineFamily",
                    "family_ref": "family:mine",
                    "owner_username": principal,
                    "owner_alias": "MaxA",
                    "factor_kind": "custom",
                    "params": [],
                }],
                "families": [{
                    "family_ref": "family:mine",
                    "factor_family_alias": "MineFamily",
                    "factor_family_name": "MineFamily",
                    "owner_username": principal,
                    "owner_alias": "MaxA",
                    "factor_kind": "custom",
                    "factor_count": 1,
                }],
            },
            "subordinates": {"factors": [], "families": []},
        }

    def factor_sets(self, _principal, _query=""):
        return [{"target_ref": "factor-set:local", "title_zh": "Local"}]


class _ConversationClientState:
    def __init__(self, owner, profile):
        self.owner = owner
        self.profile = profile

    def profiles(self, owner, *, include_local_paths):
        assert include_local_paths is False
        return [dict(self.profile)] if owner == self.owner else []


class _ConversationAgentProfiles:
    def conversations(self, owner, profile_id):
        return [{
            "conversation_id": "conversation-1",
            "profile_id": profile_id,
            "title": "Child conversation",
            "updated_at": 4,
        }]

    def conversation_items(
        self, _owner, _profile_id, _conversation_id, **_options,
    ):
        return {
            "items": [{"role": "assistant", "text": "read-only"}],
            "has_more": False,
            "after": None,
            "turn_count": 1,
        }


class _ConversationState:
    def __init__(self, owner, profile):
        self.client_state = _ConversationClientState(owner, profile)
        self.agent_profiles = _ConversationAgentProfiles()


class _ConversationRoutes(FederationPublicDataRoutesMixin):
    def __init__(self, state):
        self.state = state


def test_control_profile_projection_is_used_without_local_client_root(tmp_path):
    class ControlStore:
        def list_profiles(self, principal):
            return [{
                "principal": principal,
                "profile_id": "maxa",
                "display_name": "MaxA",
                "payload": {
                    "research_records": [{"record_id": "retired-graph-history"}],
                    "workspace_root": "/private/device/path",
                },
                "updated_at": "2026-08-14T00:00:00Z",
            }]

    service = ClientStateService(
        tmp_path / "missing-client-root",
        control_store=ControlStore(),
        profile_cache_root=tmp_path / "profile-cache",
    )
    profiles = []
    deadline = time.monotonic() + 1.0
    while not profiles and time.monotonic() < deadline:
        profiles = service.profiles("alice", include_local_paths=False)
        if not profiles:
            time.sleep(0.01)

    assert profiles[0]["profile_id"] == "maxa"
    assert "research_records" not in profiles[0]
    assert "workspace_root" not in profiles[0]


def test_direct_parent_can_read_federated_child_conversations_without_sharing_toggle(
    monkeypatch,
):
    parent = "GTHT@parent@100000000001"
    child = "GTHT@child@100000000002"
    profile = {
        "profile_id": "child-profile",
        "session_binding": {"principal_ref": child},
        "visibility": "private",
    }
    monkeypatch.setattr(
        public_data_routes,
        "direct_subordinate_accounts_for",
        lambda username: [{"username": child}] if username == parent else [],
    )
    monkeypatch.setattr(public_data_routes, "get_account", lambda _username: None)
    monkeypatch.setattr(public_data_routes, "is_super_admin_account", lambda _account: False)
    routes = _ConversationRoutes(_ConversationState(child, profile))

    value = routes._public_data_value(
        kind="catalog",
        operation="profile-conversations",
        principal=parent,
        payload={"owner": child, "profile_id": "child-profile"},
    )

    assert value["conversations"][0]["conversation_id"] == "conversation-1"


def test_federated_public_data_merges_remote_research_and_profiles_without_live_factors(
    monkeypatch,
):
    monkeypatch.setattr(
        "server.manager.services.federated_public_data.public_factor_library",
        lambda: {"factors": [], "errors": []},
    )
    gateway = _Gateway()
    service = FederatedPublicDataService(
        server_id="public-1",
        registry=_Registry(_route()),
        gateway=gateway,
        public_research=_Research(),
        client_state=_ClientState(),
    )

    reports = service.list_visible(None)
    profiles = service.profiles("alice")
    factors = service.factor_library("__public_jobs__", visitor=True)

    assert reports[0]["source_server_id"] == "internal-1"
    assert profiles[0]["profile_id"] == "maxa"
    assert factors["factors"] == []
    assert factors["families"] == []
    assert ("research", "list", "__public_jobs__") in gateway.calls
    assert ("catalog", "profiles", "alice") in gateway.calls
    assert ("catalog", "factors", "__public_jobs__") not in gateway.calls


def test_federated_factor_library_keeps_three_family_scopes(monkeypatch):
    monkeypatch.setattr(
        "server.manager.services.federated_public_data.public_factor_library",
        lambda: {"factors": [], "families": [], "errors": []},
    )
    service = FederatedPublicDataService(
        server_id="public-1",
        registry=_Registry(_route()),
        gateway=(gateway := _Gateway()),
        public_research=_Research(),
        client_state=_ClientState(),
    )

    value = service.factor_library("alice")

    assert set(value["family_scopes"]) == {"public", "mine", "subordinates"}
    assert value["family_scopes"]["mine"]["families"][0][
        "factor_family_alias"
    ] == "MineFamily"
    assert value["families"][0]["factor_family_alias"] == "MineFamily"
    assert all(
        item["owner_username"] != "__public_jobs__"
        for item in value["factors"]
    )
    assert not any(call[1] == "factors" for call in gateway.calls)


def test_factor_sets_use_synced_local_mirror_without_peer_query():
    gateway = _Gateway()
    service = FederatedPublicDataService(
        server_id="public-1",
        registry=_Registry(_route()),
        gateway=gateway,
        public_research=_Research(),
        client_state=_ClientState(),
    )

    assert service.factor_sets("alice") == [{
        "target_ref": "factor-set:local", "title_zh": "Local",
    }]
    assert not any(call[1] == "factor-sets" for call in gateway.calls)


def test_federated_public_research_detail_binds_publication_id_to_peer_payload():
    gateway = _Gateway()
    service = FederatedPublicDataService(
        server_id="public-1",
        registry=_Registry(_route()),
        gateway=gateway,
        public_research=_Research(),
        client_state=_ClientState(),
    )

    value = service.index("remote-publication", None)

    assert value == {"publication_id": "remote-publication"}
    assert gateway.payloads[-1] == {"publication_id": "remote-publication"}


def test_federated_public_research_cache_can_be_invalidated_after_mutation():
    class MutableResearch:
        def __init__(self):
            self.reports = []

        def list_visible(self, _viewer):
            return list(self.reports)

    research = MutableResearch()

    class EmptyRegistry:
        def routes(self, *, include_offline):
            return []

    service = FederatedPublicDataService(
        server_id="public-1",
        registry=EmptyRegistry(),
        gateway=_Gateway(),
        public_research=research,
        client_state=_ClientState(),
    )

    assert service.list_visible(None) == []
    research.reports = [{"publication_id": "new-publication"}]
    assert service.list_visible(None) == []

    service.invalidate_research_cache()

    assert service.list_visible(None) == [{
        "publication_id": "new-publication",
        "source_server_id": "public-1",
    }]
