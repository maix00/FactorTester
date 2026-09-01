"""Read-through projections for public research and client catalogs.

Each Manager remains authoritative for its own SQLite and report mirrors.  A
public Manager may nevertheless be the browser entry point for a user whose
Profile, factor metadata, or public research publication lives on another
Manager.  This service asks authenticated peer-control endpoints for bounded,
source-free projections and keeps the report bytes on the source node.
"""

from __future__ import annotations

import threading
from typing import Any

from server.manager.domain.federation import ServiceRoute
from server.manager.services.factor_library_scopes import (
    FAMILY_SCOPES,
    compose_factor_library_scopes,
    empty_factor_projection,
    split_factor_library_scopes,
)
from server.manager.services.federated_factor_projection import (
    VISITOR_PRINCIPAL,
    merge_factor_library_projections,
)
from server.manager.services.federated_peer_reads import FederatedPeerReadMixin
from server.manager.services.profile_directory import PROFILE_DIRECTORY_PRINCIPAL
from server.manager.services.public_catalog import public_factor_library
from server.manager.services.research_object_transfer import ResearchObjectTransfer
from tools.cli.release.research_reporting.public_research.metadata import (
    provenance_fields,
)
from tools.cli.release.research_reporting.public_research.object_store import (
    PublicResearchObjectStore,
)

DEFAULT_CACHE_SECONDS = 10.0


class FederatedPublicDataService(FederatedPeerReadMixin):
    """Merge local projections with safe projections from online peers."""

    def __init__(
        self,
        *,
        server_id: str,
        registry: object,
        gateway: object,
        public_research: object,
        client_state: object,
        account_domain_sync: object | None = None,
        object_transfer_provider: object | None = None,
        cache_seconds: float = DEFAULT_CACHE_SECONDS,
    ) -> None:
        self.server_id = str(server_id or "").strip()
        self.registry = registry
        self.gateway = gateway
        self.public_research = public_research
        self.client_state = client_state
        self.account_domain_sync = account_domain_sync
        self.object_transfer_provider = object_transfer_provider
        self.public_research_objects = PublicResearchObjectStore(public_research)
        self.research_object_transfer = ResearchObjectTransfer(
            metadata_reader=self._research_value,
            access_provider=object_transfer_provider,
            server_id=self.server_id,
            source_server_reader=self._publication_source_id,
        )
        self.cache_seconds = max(1.0, float(cache_seconds))
        self._cache: dict[tuple[object, ...], tuple[float, Any]] = {}
        self._publication_sources: dict[str, str] = {}
        self._lock = threading.RLock()

    def _peer_routes(self) -> list[ServiceRoute]:
        """Return data-read routes, including control-only peer registrations.

        Research metadata and report projections are served by the peer
        Manager's control endpoint. They must remain readable when that
        Manager has no business service port advertised (for example, while
        its execution services are stopped). The shared route registry still
        prefers a live business-port route when one exists; this fallback only
        adds one control-only route for peers that have no such route.
        """
        routes = super()._peer_routes()
        known = {route.server_id for route in routes}
        try:
            servers = self.registry.servers(include_offline=False)
        except (AttributeError, OSError, TypeError, ValueError):
            return routes
        for server in servers:
            if not isinstance(server, dict):
                continue
            server_id = str(server.get("server_id") or "").strip()
            if not server_id or server_id == self.server_id or server_id in known:
                continue
            transfer_node = server.get("transfer_node")
            if not isinstance(transfer_node, dict):
                continue
            peer_control_endpoint = str(
                transfer_node.get("peer_control_endpoint") or ""
            ).strip().rstrip("/")
            proxy_token = str(server.get("proxy_token") or "").strip()
            if not peer_control_endpoint or not proxy_token:
                continue
            load = server.get("load")
            if not isinstance(load, dict):
                load = {}
            try:
                active_jobs = max(0, int(load.get("active_jobs") or 0))
                queue_depth = max(0, int(load.get("queue_depth") or 0))
                load_value = max(0.0, float(load.get("load") or 0.0))
            except (TypeError, ValueError):
                active_jobs = queue_depth = 0
                load_value = 0.0
            routes.append(ServiceRoute(
                server_id=server_id,
                role=str(server.get("role") or ""),
                branch=str(server.get("branch") or ""),
                revision=str(server.get("revision") or ""),
                port=0,
                features=tuple(str(item) for item in server.get("features") or ()),
                endpoint=str(server.get("endpoint") or "").strip().rstrip("/"),
                peer_control_endpoint=peer_control_endpoint,
                peer_data_endpoint=str(
                    transfer_node.get("peer_data_endpoint") or ""
                ).strip().rstrip("/"),
                proxy_token=proxy_token,
                remote=True,
                online=True,
                public_server=bool(
                    server.get("public_server", server.get("role") == "main")
                ),
                load=load_value,
                active_jobs=active_jobs,
                queue_depth=queue_depth,
                latency_ms=(
                    float(server["latency_ms"])
                    if server.get("latency_ms") not in {None, ""}
                    else None
                ),
            ))
            known.add(server_id)
        return routes

    def invalidate_research_cache(self) -> None:
        """Drop cached research listings after a local publication mutation."""
        with self._lock:
            for key in tuple(self._cache):
                if key and key[0] == "research-list":
                    self._cache.pop(key, None)
            self._publication_sources.clear()

    def list_visible(self, viewer_ref: str | None) -> list[dict[str, Any]]:
        viewer = str(viewer_ref or VISITOR_PRINCIPAL)
        key = ("research-list", viewer)
        cached = self._cached(key)
        if cached is not None:
            return [dict(item) for item in cached]

        local = self.public_research.list_visible(
            None if viewer == VISITOR_PRINCIPAL else viewer,
        )
        merged: dict[str, dict[str, Any]] = {}
        # Shared publication metadata is pulled lazily from the local SQLite
        # mirror/PG cursor. It lets a public Manager list a report even when
        # the source Manager is currently offline; bytes still use the source
        # Manager's authenticated research/data path.
        if self.account_domain_sync is not None:
            try:
                rows = self.account_domain_sync.entities(
                    viewer,
                    entity_type="research_publication",
                    include_shared=True,
                    sync=False,
                )
            except (AttributeError, ConnectionError, OSError, RuntimeError, TypeError, ValueError):
                rows = []
            for row in rows:
                if not isinstance(row, dict) or row.get("deleted"):
                    continue
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    continue
                publication_id = str(
                    payload.get("publication_id") or row.get("entity_id") or ""
                ).strip()
                if not publication_id:
                    continue
                value = {
                    key: payload.get(key)
                    for key in (
                        "publication_id", "report_id", "owner_ref", "profile_ref",
                        "title", "generation", "updated_at", "visibility",
                        "is_owned", "href", "projection_hash",
                        "build_source", "build_source_ref",
                        "sharing_state", "is_shared", "authorized_users",
                    )
                    if key in payload
                }
                value.setdefault("owner_ref", row.get("principal") or "")
                value.setdefault("visibility", "private")
                value.setdefault("is_owned", value.get("owner_ref") == viewer)
                value.setdefault("href", f"/research/{publication_id}")
                value.update(provenance_fields(value))
                source_id = str(
                    payload.get("storage_server_id")
                    or row.get("origin_manager_id")
                    or ""
                ).strip()
                value["source_server_id"] = source_id
                authorized = {
                    str(item or "").strip()
                    for item in value.get("authorized_users") or []
                    if str(item or "").strip()
                }
                if (
                    value.get("visibility") == "public"
                    or value.get("is_owned")
                    or viewer in authorized
                ):
                    merged[publication_id] = value
                    if source_id:
                        with self._lock:
                            self._publication_sources[publication_id] = source_id
        for item in local:
            if not isinstance(item, dict):
                continue
            value = dict(item)
            value["source_server_id"] = self.server_id
            publication_id = str(value.get("publication_id") or "")
            if publication_id:
                merged[publication_id] = value
                with self._lock:
                    self._publication_sources[publication_id] = self.server_id

        for route, response in self._query_peers(
            kind="research", operation="list", principal=viewer,
        ):
            for raw in response.get("reports") or []:
                if not isinstance(raw, dict):
                    continue
                value = dict(raw)
                value.update(provenance_fields(value))
                value["source_server_id"] = route.server_id
                publication_id = str(value.get("publication_id") or "")
                if not publication_id:
                    continue
                merged[publication_id] = value
                with self._lock:
                    self._publication_sources[publication_id] = route.server_id

        result = sorted(
            merged.values(),
            key=lambda item: (
                str(item.get("updated_at") or ""),
                str(item.get("publication_id") or ""),
            ),
            reverse=True,
        )
        return [dict(item) for item in self._store(key, result)]

    def _publication_route(
        self, publication_id: str, viewer_ref: str | None,
    ) -> ServiceRoute | None:
        with self._lock:
            source_id = self._publication_sources.get(publication_id)
        if not source_id:
            self.list_visible(viewer_ref)
            with self._lock:
                source_id = self._publication_sources.get(publication_id)
        if not source_id or source_id == self.server_id:
            return None
        return next(
            (route for route in self._peer_routes()
             if route.server_id == source_id),
            None,
        )

    def _publication_source_id(self, publication_id: str) -> str:
        with self._lock:
            return str(self._publication_sources.get(publication_id) or "")

    def _research_value(
        self,
        publication_id: str,
        viewer_ref: str | None,
        *,
        operation: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        viewer = str(viewer_ref or VISITOR_PRINCIPAL)
        try:
            args = [
                str(item) for item in (payload or {}).get("args") or []
            ]
            library_viewer = None if viewer == VISITOR_PRINCIPAL else viewer
            if operation == "chapter":
                value = self.public_research.chapter(
                    publication_id,
                    args[0],
                    library_viewer,
                    include_content=bool(
                        (payload or {}).get("include_content", True)
                    ),
                )
            elif operation == "component":
                value = self.public_research.component(
                    publication_id, args[0], args[1], library_viewer,
                )
            elif operation == "object-metadata":
                object_kind = str((payload or {}).get("object_kind") or "").strip()
                if len(args) != 1 or not object_kind:
                    raise ValueError("research object metadata is incomplete")
                return {
                    "kind": "object",
                    "value": self.public_research_objects.metadata(
                        publication_id, object_kind, args[0], library_viewer,
                    ),
                }
            elif operation in {"asset", "attachment", "local_resource"}:
                # Object bytes are no longer a federated 7998 JSON value.  The
                # public methods below use the metadata seam and 7997 access.
                raise ValueError("research object bytes require the 7997 data plane")
            else:
                value = getattr(self.public_research, operation)(
                    publication_id, *args, library_viewer,
                )
            return {"kind": "json", "value": value}
        except PermissionError:
            raise
        except (TypeError, ValueError):
            route = self._publication_route(publication_id, viewer_ref)
            if route is None:
                with self._lock:
                    source_id = self._publication_sources.get(publication_id, "")
                if source_id and source_id != self.server_id:
                    raise ConnectionError("research source Manager is offline")
                raise
            peer_payload = dict(payload or {})
            peer_payload["publication_id"] = publication_id
            return self._query_peer(
                route,
                kind="research",
                operation=operation,
                principal=viewer,
                payload=peer_payload,
            )

    def projection(self, publication_id: str, viewer_ref: str | None) -> dict[str, Any]:
        return self._research_value(publication_id, viewer_ref, operation="projection")["value"]

    def index(self, publication_id: str, viewer_ref: str | None) -> dict[str, Any]:
        return self._research_value(publication_id, viewer_ref, operation="index")["value"]

    def chapter(
        self,
        publication_id: str,
        chapter_id: str,
        viewer_ref: str | None,
        *,
        include_content: bool = True,
    ) -> dict[str, Any]:
        response = self._research_value(
            publication_id,
            viewer_ref,
            operation="chapter",
            payload={"args": [chapter_id], "include_content": include_content},
        )
        return response["value"]

    def component(
        self,
        publication_id: str,
        chapter_id: str,
        component_id: str,
        viewer_ref: str | None,
    ) -> dict[str, Any]:
        response = self._research_value(
            publication_id,
            viewer_ref,
            operation="component",
            payload={"args": [chapter_id, component_id]},
        )
        return response["value"]

    def _research_bytes(
        self,
        publication_id: str,
        viewer_ref: str | None,
        *,
        operation: str,
        item_id: str,
    ) -> tuple[bytes, str, str]:
        object_kind = {
            "asset": "research_asset",
            "attachment": "research_attachment",
            "local_resource": "research_local_resource",
        }.get(operation)
        if object_kind is None:
            raise ValueError("research object kind is unsupported")
        return self.research_object_transfer.read(
            publication_id,
            viewer_ref,
            object_kind=object_kind,
            item_id=item_id,
        )

    def asset(self, publication_id: str, asset_id: str, viewer_ref: str | None) -> tuple[bytes, str, str]:
        return self._research_bytes(publication_id, viewer_ref, operation="asset", item_id=asset_id)

    def attachment(self, publication_id: str, attachment_ref: str, viewer_ref: str | None) -> tuple[bytes, str, str]:
        return self._research_bytes(publication_id, viewer_ref, operation="attachment", item_id=attachment_ref)

    def local_resource(self, publication_id: str, resource_id: str, viewer_ref: str | None) -> tuple[bytes, str, str]:
        return self._research_bytes(publication_id, viewer_ref, operation="local_resource", item_id=resource_id)

    def object_metadata(
        self,
        publication_id: str,
        object_kind: str,
        item_id: str,
        viewer_ref: str | None,
    ) -> dict[str, Any]:
        """Return only the metadata needed to issue a 7997 read ticket."""
        response = self._research_value(
            publication_id,
            viewer_ref,
            operation="object-metadata",
            payload={"args": [item_id], "object_kind": object_kind},
        )
        value = response.get("value")
        if not isinstance(value, dict):
            raise TypeError("research object metadata is invalid")
        return dict(value)

    def list_owner(self, owner_ref: str) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {
            str(item.get("publication_id") or ""): dict(item)
            for item in self.public_research.list_owner(owner_ref)
            if isinstance(item, dict) and str(item.get("publication_id") or "")
        }
        if self.account_domain_sync is not None:
            try:
                rows = self.account_domain_sync.entities(
                    owner_ref,
                    entity_type="research_publication",
                    include_shared=False,
                    sync=False,
                )
            except (AttributeError, ConnectionError, OSError, RuntimeError, TypeError, ValueError):
                rows = []
            for row in rows:
                if not isinstance(row, dict) or row.get("deleted"):
                    continue
                payload = row.get("payload")
                publication_id = str(
                    payload.get("publication_id")
                    if isinstance(payload, dict) else row.get("entity_id") or ""
                ).strip()
                if publication_id and isinstance(payload, dict):
                    value = dict(payload)
                    value.update(provenance_fields(value))
                    merged.setdefault(publication_id, value)
        return sorted(
            merged.values(),
            key=lambda item: str(item.get("synced_at") or item.get("updated_at") or ""),
            reverse=True,
        )

    def profiles(self, principal: str) -> list[dict[str, Any]]:
        key = ("profiles", str(principal))
        cached = self._cached(key)
        if cached is not None:
            return [dict(item) for item in cached]
        try:
            local = self.client_state.profiles(
                principal, include_local_paths=False,
            )
        except TypeError:
            # Keep the small test/legacy seam where a caller supplies a
            # principal-only profile callback.
            local = self.client_state.profiles(principal)
        merged = {
            str(item.get("profile_id") or ""): dict(item)
            for item in local
            if isinstance(item, dict) and str(item.get("profile_id") or "")
        }
        for route, response in self._query_peers(
            kind="catalog", operation="profiles", principal=principal,
        ):
            for raw in response.get("profiles") or []:
                if not isinstance(raw, dict):
                    continue
                profile_id = str(raw.get("profile_id") or "")
                if not profile_id:
                    continue
                value = dict(raw)
                value["source_server_id"] = route.server_id
                merged.setdefault(profile_id, value)
        result = sorted(
            merged.values(), key=lambda item: str(item.get("profile_id") or "")
        )
        return [dict(item) for item in self._store(key, result)]

    def profile_directory(self, owners: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
        """Read bounded Profile projections for an authorized directory view.

        The caller performs the user-facing authorization.  Federation peers
        receive only an explicit owner list and return safe Profile metadata;
        the peer never receives a browser session or a provider credential.
        """
        requested = sorted({
            str(owner or "").strip()
            for owner in owners
            if str(owner or "").strip()
        })[:2048]
        if not requested:
            return []
        merged: dict[tuple[str, str, str], dict[str, Any]] = {}
        try:
            local = self.client_state.profiles(
                requested[0], include_local_paths=False,
            ) if len(requested) == 1 else [
                item
                for owner in requested
                for item in self.client_state.profiles(owner, include_local_paths=False)
            ]
        except TypeError:
            local = [
                item
                for owner in requested
                for item in self.client_state.profiles(owner)
            ]
        for raw in local or []:
            if not isinstance(raw, dict):
                continue
            binding = raw.get("session_binding")
            owner = str(
                binding.get("principal_ref") if isinstance(binding, dict) else raw.get("owner_ref") or ""
            ).strip()
            profile_id = str(raw.get("profile_id") or "").strip()
            if owner not in requested or not profile_id:
                continue
            value = dict(raw)
            value["source_server_id"] = self.server_id
            merged[(self.server_id, owner, profile_id)] = value
        for route, response in self._query_peers(
            kind="catalog",
            operation="profiles-directory",
            principal=PROFILE_DIRECTORY_PRINCIPAL,
            payload={"owners": requested},
        ):
            for raw in response.get("profiles") or []:
                if not isinstance(raw, dict):
                    continue
                binding = raw.get("session_binding")
                owner = str(
                    binding.get("principal_ref") if isinstance(binding, dict) else raw.get("owner_ref") or ""
                ).strip()
                profile_id = str(raw.get("profile_id") or "").strip()
                if owner not in requested or not profile_id:
                    continue
                value = dict(raw)
                value["source_server_id"] = route.server_id
                merged[(route.server_id, owner, profile_id)] = value
        return sorted(
            merged.values(),
            key=lambda item: (
                str(item.get("source_server_id") or ""),
                str(item.get("profile_id") or ""),
            ),
        )

    def _profile_route(self, source_server_id: str):
        target = str(source_server_id or "").strip()
        return next(
            (route for route in self._peer_routes() if route.server_id == target),
            None,
        )

    def profile_conversations(
        self,
        source_server_id: str,
        viewer: str,
        owner: str,
        profile_id: str,
    ) -> list[dict[str, Any]]:
        cache_key = (
            "profile-conversations",
            str(source_server_id or "").strip(),
            str(viewer or "").strip(),
            str(owner or "").strip(),
            str(profile_id or "").strip(),
        )
        route = self._profile_route(source_server_id)
        if route is None:
            cached = self._stale_cached(cache_key)
            return [dict(item) for item in cached or [] if isinstance(item, dict)]
        try:
            response = self._query_peer(
                route,
                kind="catalog",
                operation="profile-conversations",
                principal=str(viewer or "").strip(),
                payload={"owner": owner, "profile_id": profile_id},
            )
            rows = [dict(item) for item in response.get("conversations") or []
                    if isinstance(item, dict)]
            return [dict(item) for item in self._store(cache_key, rows)]
        except (ConnectionError, OSError, RuntimeError, TypeError, ValueError):
            cached = self._stale_cached(cache_key)
            if cached is not None:
                return [dict(item) for item in cached if isinstance(item, dict)]
            raise

    def profile_conversation_items(
        self,
        source_server_id: str,
        viewer: str,
        owner: str,
        profile_id: str,
        conversation_id: str,
        *,
        limit: int = 10,
        after: str = "",
        view: str = "timeline",
        order: str = "desc",
    ) -> dict[str, Any]:
        route = self._profile_route(source_server_id)
        if route is None:
            raise ConnectionError("conversation source server is offline")
        response = self._query_peer(
            route,
            kind="catalog",
            operation="profile-conversation-items",
            principal=str(viewer or "").strip(),
            payload={
                "owner": owner,
                "profile_id": profile_id,
                "conversation_id": conversation_id,
                "limit": max(1, min(int(limit), 50)),
                "after": str(after or ""),
                "view": str(view or "timeline"),
                "order": str(order or "desc"),
            },
        )
        return {
            "items": [dict(item) for item in response.get("items") or []
                      if isinstance(item, dict)],
            "has_more": bool(response.get("has_more")),
            "after": response.get("after"),
            "turn_count": int(response.get("turn_count") or 0),
            "view": str(response.get("view") or view or "timeline"),
            "order": str(response.get("order") or order or "desc"),
        }

    def factor_library(
        self, principal: str, *, visitor: bool = False,
        refresh: bool = False,
    ) -> dict[str, Any]:
        viewer = VISITOR_PRINCIPAL if visitor else str(principal)
        key = ("factors", viewer)
        cached = None if refresh else self._cached(key)
        if cached is not None:
            return dict(cached)
        public = public_factor_library()
        local_scopes = {"public": public}
        if not visitor:
            scope_reader = getattr(
                self.client_state, "factor_library_scopes", None,
            )
            if callable(scope_reader):
                local_scopes.update(
                    scope_reader(principal, refresh=refresh)
                    if refresh else scope_reader(principal)
                )
            else:
                # Keep a bounded fallback for older test seams and Managers.
                local_scopes["mine"] = (
                    self.client_state.factor_library(principal, refresh=True)
                    if refresh else self.client_state.factor_library(principal)
                )
        local = compose_factor_library_scopes(
            local_scopes, principal=str(principal or viewer),
        )
        # Factor metadata is account-domain state, not live service state.
        # Each Manager reads its SQLite mirror; waiting for every peer here
        # makes a picker depend on peer reachability and duplicates synced rows.
        projections = [local]
        scoped_values = {scope: [] for scope in FAMILY_SCOPES}
        for value in projections:
            scopes = split_factor_library_scopes(
                value,
                principal=str(principal or viewer),
                visitor=visitor,
            )
            for scope, projection in scopes.items():
                scoped_values.setdefault(scope, []).append(projection)
        merged_scopes = {
            scope: merge_factor_library_projections(
                scoped_values.get(scope) or [empty_factor_projection(principal)],
                principal=str(principal or viewer),
            )
            for scope in FAMILY_SCOPES
            if not visitor or scope == "public"
        }
        result = merge_factor_library_projections(
            list(merged_scopes.values()), principal=str(principal or viewer),
        )
        result["family_scopes"] = merged_scopes
        return dict(self._store(key, result))

    def factor_sets(self, principal: str, query: str = "") -> list[dict[str, Any]]:
        # Immutable sets share the same account-domain mirror as factors.
        # They must not reintroduce a peer wait after the factor list is ready.
        return self.client_state.factor_sets(principal, query)

    def factor_set_scopes(
        self, principal: str, query: str = "",
    ) -> dict[str, list[dict[str, Any]]]:
        """Read synchronized own/direct-child scopes without querying peers."""
        return self.client_state.factor_set_scopes(principal, query)
