"""Federated data-source catalog projection for Manager state."""

from __future__ import annotations

import os
from typing import Protocol
from urllib.parse import urlparse

from server.manager.domain.federation import ServiceRoute
from server.manager.domain.federation.capability_catalog import (
    load_peer_capability_snapshots,
)


class SourceCatalogState(Protocol):
    server_id: str
    server_role: str
    fixed_branch: str
    public_server: bool
    client_state: object
    federation_registry: object

    def local_service_routes(self, *, include_offline: bool = True) -> list[ServiceRoute]: ...
    def local_capability_snapshot(self, payload: dict[str, object] | None = None) -> dict[str, object]: ...
    def _revision_for_path(self, path: object = None) -> str: ...
    def _cached_peer_capabilities(self, route: ServiceRoute, *, refresh: bool = False) -> dict[str, object] | None: ...
    def route_selection_key(self, route: ServiceRoute) -> tuple[float, float, int, str, int]: ...


def merge_source_values(first: object, second: object) -> list[str]:
    values: list[str] = []
    for collection in (first, second):
        if not isinstance(collection, (list, tuple, set)):
            continue
        for value in collection:
            text = str(value or "").strip()
            if text and text not in values:
                values.append(text)
    return values


def merge_source_objects(
    first: object,
    second: object,
    *,
    key_fields: tuple[str, ...],
) -> list[dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}
    for collection in (first, second):
        if not isinstance(collection, (list, tuple)):
            continue
        for value in collection:
            if not isinstance(value, dict):
                continue
            key = next(
                (
                    str(value.get(field) or "").strip()
                    for field in key_fields
                    if str(value.get(field) or "").strip()
                ),
                "",
            )
            if key:
                merged[key] = {**merged.get(key, {}), **value}
    return list(merged.values())


def merge_source_availability(first: object, second: object) -> dict[str, object]:
    left = first if isinstance(first, dict) else {}
    right = second if isinstance(second, dict) else {}
    status = (
        "ready"
        if "ready" in {left.get("status"), right.get("status")}
        else str(left.get("status") or right.get("status") or "")
    )
    return {
        **left,
        **right,
        "status": status,
        "product_count": max(
            int(left.get("product_count") or 0),
            int(right.get("product_count") or 0),
        ),
        "frequency_names": merge_source_values(
            left.get("frequency_names"), right.get("frequency_names")
        ),
    }


def source_provider(
    route: ServiceRoute,
    *,
    source: dict[str, object] | None = None,
    ports: list[int] | None = None,
    routes: list[ServiceRoute] | None = None,
    online: bool | None = None,
) -> dict[str, object]:
    endpoint = str(route.endpoint or "")
    source = source or {}
    target_routes = list(routes or [route])
    target_ports = sorted({item.port for item in target_routes})
    return {
        "server_id": route.server_id,
        "server_role": route.role,
        "server_branch": route.branch,
        "server_revision": route.revision,
        "server_endpoint": endpoint,
        "server_host": urlparse(endpoint).hostname or "",
        "online": route.online if online is None else bool(online),
        "ports": sorted({
            int(value)
            for value in (ports or target_ports or [route.port])
            if 1 <= int(value) <= 65535
        }),
        "targets": [
            {
                "server_id": item.server_id,
                "port": item.port,
                "branch": item.branch,
                "revision": item.revision,
                "features": list(item.features),
                "online": item.online,
                "load": item.load,
                "queue_depth": item.queue_depth,
            }
            for item in sorted(target_routes, key=lambda item: (item.port, item.branch))
        ],
        "frequencies": list(source.get("frequencies") or []),
        "catalog_product_count": int(source.get("catalog_product_count") or 0),
        "available_product_count": int(source.get("available_product_count") or 0),
        "capability_revision": str(source.get("revision") or ""),
        "public_server": bool(route.public_server),
    }


def federated_source_descriptors(
    state: SourceCatalogState,
    *,
    refresh: bool = False,
) -> list[dict[str, object]]:
    """Merge local and peer source catalogs with provider metadata."""
    local_ports = state.local_service_routes(include_offline=True)
    peer_routes = state.federation_registry.routes(include_offline=True)
    local_sources = state.client_state.product_sources() or []
    if not local_ports and not peer_routes:
        return [dict(item) for item in local_sources if isinstance(item, dict)]

    local_snapshot = state.local_capability_snapshot({"summary": True})
    local_by_id = {
        str(item.get("id") or ""): dict(item)
        for item in local_sources
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    summary_by_id = {
        str(item.get("id") or ""): item
        for item in (local_snapshot.get("sources") or [])
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    merged: dict[str, dict[str, object]] = {}
    local_endpoint = (
        str(os.environ.get("FACTORTESTER_MANAGER_PUBLIC_ENDPOINT") or "")
        .strip()
        .rstrip("/")
        or "http://127.0.0.1:7998"
    )
    local_route = ServiceRoute(
        server_id=state.server_id,
        role=state.server_role,
        branch=state.fixed_branch,
        revision=state._revision_for_path(),
        port=7998,
        endpoint=local_endpoint,
        online=True,
        public_server=bool(state.public_server),
        latency_ms=0.0,
    )
    local_port_values = [route.port for route in local_ports]
    for source_id, summary in summary_by_id.items():
        base = dict(local_by_id.get(source_id) or summary)
        base.setdefault("source_ref", f"data-source:server:{source_id}")
        base.setdefault("bundle_id", source_id)
        base.setdefault("bundle_name", base.get("source_name") or source_id)
        base["server_providers"] = [source_provider(
            local_route,
            source=summary,
            ports=local_port_values or [7998],
            routes=local_ports or [local_route],
            online=any(route.online for route in local_ports) if local_ports else True,
        )]
        merged[source_id] = base

    peer_route_groups: dict[str, list[ServiceRoute]] = {}
    for route in peer_routes:
        peer_route_groups.setdefault(route.server_id, []).append(route)
    selected_routes = {
        server_id: min(routes, key=state.route_selection_key)
        for server_id, routes in peer_route_groups.items()
    }
    snapshots = load_peer_capability_snapshots(
        selected_routes.values(),
        lambda route: state._cached_peer_capabilities(route, refresh=refresh),
    )
    for server_id, routes in peer_route_groups.items():
        route = selected_routes[server_id]
        snapshot = snapshots.get(server_id)
        peer_sources = {
            str(item.get("id") or ""): item
            for item in ((snapshot or {}).get("sources") or [])
            if isinstance(item, dict) and str(item.get("id") or "")
        }
        for source_id, summary in peer_sources.items():
            base = merged.setdefault(source_id, {
                "id": source_id,
                "source_name": summary.get("source_name") or source_id,
                "source_ref": f"data-source:server:{source_id}",
                "bundle_id": source_id,
                "bundle_name": summary.get("source_name") or source_id,
                "provider_kind": summary.get("provider_kind") or "",
                "members": summary.get("members") or [],
                "frequencies": summary.get("frequencies") or [],
                "availability": summary.get("availability") or {},
                "catalog_product_count": summary.get("catalog_product_count") or 0,
            })
            if source_id not in local_by_id:
                for key in ("provider_kind", "frequencies"):
                    if key in summary:
                        base[key] = summary[key]
            base["members"] = merge_source_objects(
                base.get("members"), summary.get("members"),
                key_fields=("id", "key", "label"),
            )
            base["product_paths"] = merge_source_values(
                base.get("product_paths"), summary.get("product_paths")
            )
            base["categories"] = merge_source_objects(
                base.get("categories"), summary.get("categories"),
                key_fields=("id", "title_zh", "title"),
            )
            base["data_modes"] = merge_source_objects(
                base.get("data_modes"), summary.get("data_modes"),
                key_fields=("id", "frequency", "title_zh"),
            )
            base["frequencies"] = merge_source_values(
                base.get("frequencies"), summary.get("frequencies")
            )
            base["catalog_product_count"] = max(
                int(base.get("catalog_product_count") or 0),
                int(summary.get("catalog_product_count") or 0),
            )
            base["availability"] = merge_source_availability(
                base.get("availability"), summary.get("availability")
            )
            base.setdefault("server_providers", []).append(source_provider(
                route,
                source=summary,
                routes=routes,
                online=any(item.online for item in routes),
            ))

    for source in merged.values():
        providers = source.get("server_providers") or []
        source["server_providers"] = sorted(
            providers,
            key=lambda item: (
                not bool(item.get("online")),
                str(item.get("server_id") or ""),
            ),
        )
        source["server_provided"] = bool(source.get("server_provided")) or any(
            bool(item.get("online")) for item in providers
        )
    return sorted(
        merged.values(),
        key=lambda item: str(item.get("source_name") or item.get("id") or ""),
    )
