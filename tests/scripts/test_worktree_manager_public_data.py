"""Federated public research, Profile, and factor projections."""

from __future__ import annotations

from server.manager.domain.federation import ServiceRoute
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
                "research_records": [{"record_id": "r1"}],
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


def test_control_profile_projection_is_used_without_local_client_root(tmp_path):
    class ControlStore:
        def list_profiles(self, principal):
            return [{
                "principal": principal,
                "profile_id": "maxa",
                "display_name": "MaxA",
                "payload": {
                    "research_records": [{"record_id": "r1"}],
                    "workspace_root": "/private/device/path",
                },
                "updated_at": "2026-08-14T00:00:00Z",
            }]

    service = ClientStateService(
        tmp_path / "missing-client-root",
        control_store=ControlStore(),
    )
    profiles = service.profiles("alice", include_local_paths=False)

    assert profiles[0]["profile_id"] == "maxa"
    assert profiles[0]["research_records"] == [{"record_id": "r1"}]
    assert "workspace_root" not in profiles[0]


def test_federated_public_data_merges_remote_research_profiles_and_factors(
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
    assert factors["factors"][0]["factor_alias"] == "RemoteMomentum"
    assert ("research", "list", "__public_jobs__") in gateway.calls
    assert ("catalog", "profiles", "alice") in gateway.calls
    assert ("catalog", "factors", "__public_jobs__") in gateway.calls


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
