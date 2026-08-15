"""Read-through projections for public research and client catalogs.

Each Manager remains authoritative for its own SQLite and report mirrors.  A
public Manager may nevertheless be the browser entry point for a user whose
Profile, factor metadata, or public research publication lives on another
Manager.  This service asks authenticated peer-control endpoints for bounded,
source-free projections and keeps the report bytes on the source node.
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time
from typing import Any

from server.manager.domain.federation import ServiceRoute
from server.manager.services.public_catalog import public_factor_library


VISITOR_PRINCIPAL = "__public_jobs__"
DEFAULT_CACHE_SECONDS = 10.0


class FederatedPublicDataService:
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
        cache_seconds: float = DEFAULT_CACHE_SECONDS,
    ) -> None:
        self.server_id = str(server_id or "").strip()
        self.registry = registry
        self.gateway = gateway
        self.public_research = public_research
        self.client_state = client_state
        self.account_domain_sync = account_domain_sync
        self.cache_seconds = max(1.0, float(cache_seconds))
        self._cache: dict[tuple[object, ...], tuple[float, Any]] = {}
        self._publication_sources: dict[str, str] = {}
        self._lock = threading.RLock()

    def _cached(self, key: tuple[object, ...]) -> Any | None:
        with self._lock:
            item = self._cache.get(key)
            if item is None or time.monotonic() - item[0] >= self.cache_seconds:
                return None
            return item[1]

    def _store(self, key: tuple[object, ...], value: Any) -> Any:
        with self._lock:
            self._cache[key] = (time.monotonic(), value)
        return value

    def invalidate_research_cache(self) -> None:
        """Drop cached research listings after a local publication mutation."""
        with self._lock:
            for key in tuple(self._cache):
                if key and key[0] == "research-list":
                    self._cache.pop(key, None)
            self._publication_sources.clear()

    def _peer_routes(self) -> list[ServiceRoute]:
        """Choose one live control route per peer; stale leases never block."""
        try:
            routes = self.registry.routes(include_offline=False)
        except (AttributeError, OSError, TypeError, ValueError):
            return []
        grouped: dict[str, list[ServiceRoute]] = {}
        for route in routes:
            if route.server_id == self.server_id or not route.online:
                continue
            grouped.setdefault(route.server_id, []).append(route)
        result: list[ServiceRoute] = []
        for values in grouped.values():
            result.append(min(values, key=self._route_key))
        return result

    @staticmethod
    def _route_key(route: ServiceRoute) -> tuple[float, float, int, str, int]:
        return (
            float(route.latency_ms)
            if route.latency_ms is not None else float("inf"),
            float(route.load),
            int(route.queue_depth),
            str(route.server_id),
            int(route.port),
        )

    def _query_peer(
        self,
        route: ServiceRoute,
        *,
        kind: str,
        operation: str,
        principal: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        value = self.gateway.public_data(
            route,
            kind=kind,
            operation=operation,
            principal=principal,
            payload=payload,
        )
        return value if isinstance(value, dict) else {}

    def _query_peers(
        self,
        *,
        kind: str,
        operation: str,
        principal: str,
        payload: dict[str, object] | None = None,
    ) -> list[tuple[ServiceRoute, dict[str, Any]]]:
        routes = self._peer_routes()
        if not routes:
            return []
        result: list[tuple[ServiceRoute, dict[str, Any]]] = []
        with ThreadPoolExecutor(max_workers=min(len(routes), 8)) as pool:
            futures = {
                pool.submit(
                    self._query_peer,
                    route,
                    kind=kind,
                    operation=operation,
                    principal=principal,
                    payload=payload,
                ): route
                for route in routes
            }
            for future in as_completed(futures):
                route = futures[future]
                try:
                    result.append((route, future.result()))
                except (ConnectionError, OSError, RuntimeError, TypeError, ValueError):
                    continue
        return result

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
                self.account_domain_sync.reconcile_research_library(
                    self.public_research,
                )
                rows = self.account_domain_sync.entities(
                    viewer,
                    entity_type="research_publication",
                    include_shared=True,
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
                    )
                    if key in payload
                }
                value.setdefault("owner_ref", row.get("principal") or "")
                value.setdefault("visibility", "private")
                value.setdefault("is_owned", value.get("owner_ref") == viewer)
                value.setdefault("href", f"/research/{publication_id}")
                source_id = str(
                    payload.get("storage_server_id")
                    or row.get("origin_manager_id")
                    or ""
                ).strip()
                value["source_server_id"] = source_id
                if value.get("visibility") == "public" or value.get("is_owned"):
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
        viewer = str(viewer_ref or VISITOR_PRINCIPAL)
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
            elif operation in {"asset", "attachment", "local_resource"}:
                raw, content_type, filename = getattr(self.public_research, operation)(
                    publication_id, args[0], library_viewer,
                )
                return {
                    "kind": "bytes",
                    "raw_b64": base64.b64encode(raw).decode("ascii"),
                    "content_type": content_type,
                    "filename": filename,
                }
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
        response = self._research_value(
            publication_id,
            viewer_ref,
            operation=operation,
            payload={"args": [item_id]},
        )
        if response.get("kind") != "bytes":
            raise ValueError("federated research response is invalid")
        try:
            raw = base64.b64decode(
                str(response.get("raw_b64") or "").encode("ascii"),
                validate=True,
            )
        except (ValueError, UnicodeEncodeError) as exc:
            raise ValueError("federated research bytes are invalid") from exc
        return raw, str(response.get("content_type") or "application/octet-stream"), str(
            response.get("filename") or item_id
        )

    def asset(self, publication_id: str, asset_id: str, viewer_ref: str | None) -> tuple[bytes, str, str]:
        return self._research_bytes(publication_id, viewer_ref, operation="asset", item_id=asset_id)

    def attachment(self, publication_id: str, attachment_ref: str, viewer_ref: str | None) -> tuple[bytes, str, str]:
        return self._research_bytes(publication_id, viewer_ref, operation="attachment", item_id=attachment_ref)

    def local_resource(self, publication_id: str, resource_id: str, viewer_ref: str | None) -> tuple[bytes, str, str]:
        return self._research_bytes(publication_id, viewer_ref, operation="local_resource", item_id=resource_id)

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
                    merged.setdefault(publication_id, dict(payload))
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

    def factor_library(
        self, principal: str, *, visitor: bool = False,
    ) -> dict[str, Any]:
        viewer = VISITOR_PRINCIPAL if visitor else str(principal)
        key = ("factors", viewer)
        cached = self._cached(key)
        if cached is not None:
            return dict(cached)
        local = (
            public_factor_library()
            if visitor else self.client_state.factor_library(principal)
        )
        factor_rows = [
            dict(item) for item in (local.get("factors") or [])
            if isinstance(item, dict)
        ]
        errors = list(local.get("errors") or [])
        peer_values = self._query_peers(
            kind="catalog", operation="factors", principal=viewer,
        )
        if not peer_values:
            return dict(self._store(key, dict(local)))
        for _route, response in peer_values:
            factor_rows.extend(
                dict(item) for item in (response.get("factors") or [])
                if isinstance(item, dict)
            )
            errors.extend(item for item in response.get("errors") or [])
        for item in factor_rows:
            if "source" not in item and item.get("factor_kind") in {
                "custom", "public",
            }:
                item["source"] = item["factor_kind"]
        from server.modules.custom_factors.client_library import (
            build_client_library_projection,
        )
        result = build_client_library_projection(
            {"factors": factor_rows, "errors": errors},
            principal=viewer,
        )
        return dict(self._store(key, result))

    def factor_sets(self, principal: str, query: str = "") -> list[dict[str, Any]]:
        local = self.client_state.factor_sets(principal, query)
        merged = {
            str(item.get("target_ref") or item.get("id") or ""): dict(item)
            for item in local if isinstance(item, dict)
        }
        peer_values = self._query_peers(
            kind="catalog", operation="factor-sets", principal=principal,
            payload={"query": query},
        )
        if not peer_values:
            return list(merged.values())
        for _route, response in peer_values:
            for item in response.get("items") or []:
                if isinstance(item, dict):
                    key = str(item.get("target_ref") or item.get("id") or "")
                    if key:
                        merged.setdefault(key, dict(item))
        return list(merged.values())
