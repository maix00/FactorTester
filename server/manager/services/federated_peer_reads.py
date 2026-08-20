"""Bounded cache and concurrent peer reads shared by federated catalogs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from typing import Any

from server.manager.domain.federation import ServiceRoute


class FederatedPeerReadMixin:
    """Provide one-route-per-peer fan-out with fresh and stale caches."""

    def _cached(self, key: tuple[object, ...]) -> Any | None:
        with self._lock:
            item = self._cache.get(key)
            if item is None or time.monotonic() - item[0] >= self.cache_seconds:
                return None
            return item[1]

    def _stale_cached(
        self,
        key: tuple[object, ...],
        *,
        max_age: float = 300.0,
    ) -> Any | None:
        """Return a bounded read cache only when a peer refresh failed."""
        with self._lock:
            item = self._cache.get(key)
            if item is None:
                return None
            if time.monotonic() - item[0] >= max(1.0, float(max_age)):
                self._cache.pop(key, None)
                return None
            return item[1]

    def _store(self, key: tuple[object, ...], value: Any) -> Any:
        with self._lock:
            self._cache[key] = (time.monotonic(), value)
        return value

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
        return [min(values, key=self._route_key) for values in grouped.values()]

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
