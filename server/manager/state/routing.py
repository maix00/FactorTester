"""Service capability discovery and federation route selection."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path
from server.manager.domain.capabilities import capability_snapshot
from server.manager.domain.federation import (
    ServiceRoute,
    TargetNotFound,
    TargetUnavailable,
)
from server.manager.http.gateway import GatewayResponse
from server.manager.state.federated_source_catalog import (
    federated_source_descriptors as build_federated_source_descriptors,
    source_provider,
)
from server.manager.state.models import Worktree


class RoutingStateMixin:
    """Project local and peer capabilities into deterministic service routes."""
    def _revision_for_path(self, path: Path | None = None) -> str:
        target = (path or self.repo).resolve()
        try:
            return subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=target,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            return str(os.environ.get("GTHT_SOURCE_REVISION") or "").strip()

    @staticmethod
    def _daemon_health_socket(path: str | Path) -> dict[str, object] | None:
        target = Path(path).expanduser()
        if not target.exists():
            return None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
                channel.settimeout(0.5)
                channel.connect(str(target))
                channel.sendall(b'{"action":"health"}\n')
                chunks = bytearray()
                while len(chunks) < 1024 * 1024:
                    part = channel.recv(65536)
                    if not part:
                        break
                    chunks.extend(part)
                    if b"\n" in part:
                        break
        except (OSError, socket.timeout):
            return None
        try:
            value = json.loads(bytes(chunks).partition(b"\n")[0].decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) and value.get("success", True) else None

    @staticmethod
    def _load_from_health(value: dict[str, object] | None) -> dict[str, object]:
        if not value:
            return {"load": 50.0, "active_jobs": 0, "queue_depth": 0}
        try:
            active = max(
                0,
                int(value.get("active_executors") or 0)
                + int(value.get("active_planners") or 0),
            )
            queued = max(
                0,
                int(value.get("queue_depth") or value.get("queued_jobs") or 0),
            )
        except (TypeError, ValueError):
            return {"load": 50.0, "active_jobs": 0, "queue_depth": 0}
        payload = {
            "load": float(active * 2 + queued),
            "active_jobs": active,
            "queue_depth": queued,
        }
        return payload

    def local_service_load(self, port: int) -> dict[str, object]:
        health: dict[str, object] | None = None
        if self.fixed_port and int(port) == self.fixed_port and self.fixed_daemon_socket:
            health = self._daemon_health_socket(self.fixed_daemon_socket)
        else:
            try:
                worktrees = self.worktrees()
            except (OSError, subprocess.CalledProcessError):
                # A few callers provide a legacy live-port seam without a
                # Git checkout (and it is also useful during first bootstrap).
                worktrees = []
            worktree = next(
                (item for item in worktrees if item.port == int(port)),
                None,
            )
            if worktree is not None:
                bundle = self._bundle_for_path(worktree.path)
                if bundle is not None:
                    try:
                        health = self._daemon_request(bundle, "health")
                    except (OSError, RuntimeError, ValueError):
                        health = None
        return self._load_from_health(health)

    def _local_route(
        self,
        *,
        port: int,
        branch: str = "",
        revision: str = "",
        features: tuple[str, ...] = (),
        online: bool | None = None,
    ) -> ServiceRoute:
        metrics = self.local_service_load(int(port))
        return ServiceRoute(
            server_id=self.server_id,
            role=self.server_role,
            branch=branch,
            revision=revision or self._revision_for_path(),
            port=int(port),
            endpoint=str(
                os.environ.get("FACTORTESTER_MANAGER_PUBLIC_ENDPOINT")
                or "http://127.0.0.1:7998"
            ).strip().rstrip("/"),
            features=tuple(sorted({*self.server_features, *features})),
            public_server=bool(self.public_server),
            online=self._port_is_in_use(int(port)) if online is None else bool(online),
            load=float(metrics.get("load") or 0.0),
            active_jobs=int(metrics.get("active_jobs") or 0),
            queue_depth=int(metrics.get("queue_depth") or 0),
            latency_ms=0.0,
        )
    def local_service_routes(self, *, include_offline: bool = True) -> list[ServiceRoute]:
        """Describe services owned by this Manager, including stopped targets."""
        routes: list[ServiceRoute] = []
        seen: set[int] = set()
        if self.fixed_port:
            routes.append(self._local_route(
                port=self.fixed_port,
                branch=self.fixed_branch,
                online=self._port_is_in_use(self.fixed_port),
            ))
            seen.add(self.fixed_port)
        try:
            worktrees = self.worktrees()
        except (OSError, subprocess.CalledProcessError):
            worktrees = []
        for worktree in worktrees:
            if not worktree.port or worktree.port in seen:
                continue
            routes.append(self._local_route(
                port=worktree.port,
                branch=worktree.branch,
                revision=self._revision_for_path(worktree.path),
                online=self._port_is_in_use(worktree.port),
            ))
            seen.add(worktree.port)
        if include_offline:
            return sorted(routes, key=lambda item: item.port)
        return [item for item in routes if item.online]

    def service_routes(self, *, include_offline: bool = False) -> list[ServiceRoute]:
        """Return local and registered remote service routes."""
        routes = self.local_service_routes(include_offline=include_offline)
        routes.extend(self.federation_registry.routes(
            include_offline=include_offline,
        ))
        return sorted(routes, key=lambda item: (item.server_id, item.port))

    def local_capability_snapshot(
        self, payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Return the source capability projection owned by this host."""
        return capability_snapshot(payload)

    def _cached_peer_capabilities(
        self,
        route: ServiceRoute,
        *,
        refresh: bool = False,
    ) -> dict[str, object] | None:
        now = time.time()
        cache_key = (route.server_id, int(route.port), route.branch)
        with self._capability_cache_lock:
            cached = self._capability_cache.get(cache_key)
            if cached is not None and not refresh and now - cached[0] < 15.0:
                return dict(cached[1])
        if not route.online:
            return dict(cached[1]) if cached is not None else None
        try:
            value = self.federation_gateway.capabilities(
                route,
                payload={
                    "summary": True,
                    "server_id": route.server_id,
                    "port": route.port,
                    "branch": route.branch,
                },
            )
        except (ConnectionError, OSError, ValueError, TypeError):
            return dict(cached[1]) if cached is not None else None
        with self._capability_cache_lock:
            self._capability_cache[cache_key] = (now, dict(value))
        return value

    @staticmethod
    def _source_provider(
        route: ServiceRoute,
        *,
        source: dict[str, object] | None = None,
        ports: list[int] | None = None,
        routes: list[ServiceRoute] | None = None,
        online: bool | None = None,
    ) -> dict[str, object]:
        return source_provider(
            route,
            source=source,
            ports=ports,
            routes=routes,
            online=online,
        )

    def federated_source_descriptors(
        self, *, refresh: bool = False,
    ) -> list[dict[str, object]]:
        return build_federated_source_descriptors(self, refresh=refresh)

    def route_for(
        self,
        *,
        port: int | None = None,
        server_id: str = "",
        branch: str = "",
        feature: str = "",
    ) -> ServiceRoute:
        """Resolve one target, rejecting explicitly offline services."""
        server_id = str(server_id or "").strip()
        branch = str(branch or "").strip()
        feature = str(feature or "").strip()
        local = self.local_service_routes(include_offline=True)
        candidates = local
        if server_id and server_id not in {self.server_id, "local"}:
            candidates = []
        if port is not None:
            candidates = [item for item in candidates if item.port == int(port)]
        if branch:
            candidates = [item for item in candidates if item.branch == branch]
        if feature:
            candidates = [item for item in candidates if feature in item.features]
        if candidates:
            online = [item for item in candidates if item.online]
            if not online:
                identity = server_id or branch or feature or f"port {port}"
                raise TargetUnavailable(f"target {identity} is offline")
            return sorted(online, key=lambda item: item.port)[0]

        # Keep the small unit-test and legacy-manager seam where callers can
        # provide a live port without Git worktree metadata.
        if (
            port is not None
            and server_id in {"", self.server_id, "local"}
            and not branch
            and not feature
            and int(port) in self.service_ports()
        ):
            return self._local_route(
                port=int(port),
                branch=branch or self.fixed_branch,
                online=True,
            )

        if server_id or port is not None or branch or feature:
            try:
                return self.federation_registry.find(
                    server_id=server_id,
                    port=port,
                    branch=branch,
                    feature=feature,
                    online_only=True,
                )
            except (TargetNotFound, TargetUnavailable) as original:
                activated = self._activate_discovered_route(
                    server_id=server_id,
                    port=port,
                    branch=branch,
                    feature=feature,
                )
                if activated is not None:
                    return activated
                raise original

        peer_routes = self.federation_registry.routes(include_offline=True)
        if peer_routes:
            online = [route for route in [*local, *peer_routes] if route.online]
            if not online:
                raise TargetUnavailable("all peer service targets are offline")
            return sorted(
                online,
                key=self.route_selection_key,
            )[0]
        preferred = self.preferred_service_port()
        if preferred is not None:
            return self.route_for(port=preferred)
        activated = self._activate_discovered_route()
        if activated is not None:
            return activated
        raise TargetNotFound("no online service target")

    def _activate_discovered_route(
        self,
        *,
        server_id: str = "",
        port: int | None = None,
        branch: str = "",
        feature: str = "",
    ) -> ServiceRoute | None:
        candidates = self.federation_directory.candidates(
            server_id=server_id,
            port=port,
            branch=branch,
            feature=feature,
        )
        failures: list[str] = []
        for node in candidates:
            node_id = str(node.get("server_id") or "")
            try:
                self.activate_federated_node(node_id)
                return self.federation_registry.find(
                    server_id=node_id,
                    port=port,
                    branch=branch,
                    feature=feature,
                    online_only=True,
                )
            except (TargetNotFound, TargetUnavailable) as exc:
                failures.append(str(exc))
        if failures:
            raise TargetUnavailable("; ".join(failures))
        return None

    @staticmethod
    def route_selection_key(route: ServiceRoute) -> tuple[float, float, int, str, int]:
        """Prefer the nearest Manager, then the least-loaded service."""
        return (
            float(route.latency_ms)
            if route.latency_ms is not None else float("inf"),
            float(route.load),
            int(route.queue_depth),
            str(route.server_id),
            int(route.port),
        )

    def route_request(
        self,
        route: ServiceRoute,
        *,
        path: str,
        principal: str,
        method: str | None = None,
        body: bytes | None = None,
        content_type: str = "application/json",
        origin_server_id: str = "",
    ) -> GatewayResponse:
        forwarded: dict[str, object] = {
            "path": path,
            "principal": principal,
        }
        if method is not None:
            forwarded["method"] = method
        if body is not None:
            forwarded["body"] = body
            forwarded["content_type"] = content_type
        if route.remote:
            if str(origin_server_id or "").strip():
                forwarded["origin_server_id"] = str(origin_server_id).strip()
            return self.federation_gateway.request(
                route,
                **forwarded,
            )
        return self.gateway.request(
            port=route.port,
            **forwarded,
        )

    def route_json(
        self,
        route: ServiceRoute,
        *,
        path: str,
        principal: str,
    ) -> dict[str, object]:
        if route.remote:
            return self.federation_gateway.json(
                route,
                path=path,
                principal=principal,
            )
        return self.service_json(route.port, path, principal)

    def service_ports(self) -> list[int]:
        try:
            worktrees = self.worktrees()
        except (OSError, subprocess.CalledProcessError):
            worktrees = []
        ports = {
            worktree.port for worktree in worktrees
            if worktree.port and self._port_is_in_use(worktree.port)
        }
        if self.fixed_port and self._port_is_in_use(self.fixed_port):
            ports.add(self.fixed_port)
        return sorted(ports)

    def preferred_service_port(self) -> int | None:
        try:
            worktrees = self.worktrees()
        except (OSError, subprocess.CalledProcessError):
            worktrees = []
        running = {
            item.port: item for item in worktrees
            if item.port and self._port_is_in_use(item.port)
        }
        if self.fixed_port and self._port_is_in_use(self.fixed_port):
            running.setdefault(self.fixed_port, Worktree(
                path=self.repo,
                branch=self.fixed_branch or self.server_role,
                head=self._revision_for_path()[:8],
                label=self.fixed_branch or self.server_role,
                port=self.fixed_port,
            ))
        if not running:
            return None
        def priority(port: int) -> tuple[int, int]:
            branch = running[port].branch.lower()
            if branch == "main":
                return (0, port)
            if branch == "feat" or branch.startswith("feat/"):
                return (1, port)
            return (2, port)
        return min(running, key=priority)

    def ordered_job_service_ports(self) -> list[int]:
        """Return the preferred service first, tolerating stale Git metadata."""
        preferred = self.preferred_service_port()
        try:
            available = self.service_ports()
        except (OSError, subprocess.CalledProcessError):
            # A temporary/test repository may not have Git worktree metadata;
            # the preferred port is still a valid candidate.
            available = []
        return [
            *([preferred] if preferred is not None else []),
            *[value for value in available if value != preferred],
        ]

    def service_json(
        self, port: int, path: str, principal: str,
    ) -> dict[str, object]:
        return self.gateway.json(
            port=port, path=path, principal=principal,
        )
