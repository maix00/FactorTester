"""Service capability discovery and federation route selection."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from server.jobs.artifact_data_plane import artifact_data_endpoint, artifact_data_port
from server.manager.domain.capabilities import capability_snapshot
from server.manager.domain.federation import (
    FederationAnnouncer,
    ServiceRoute,
    TargetNotFound,
    TargetUnavailable,
)
from server.manager.http.gateway import GatewayResponse
from server.manager.services.network_info import (
    local_internal_addresses,
    public_manager_targets,
    server_network_info as build_server_network_info,
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
            return ""

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
            artifact_endpoint=artifact_data_endpoint(
                endpoint=os.environ.get("FACTORTESTER_MANAGER_PUBLIC_ENDPOINT")
                or "http://127.0.0.1:7998",
                port=artifact_data_port(),
            ),
            artifact_port=artifact_data_port(),
            features=tuple(sorted({*self.server_features, *features})),
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
        endpoint = str(route.endpoint or "")
        host = urlparse(endpoint).hostname or ""
        source = source or {}
        target_routes = list(routes or [route])
        target_ports = sorted({item.port for item in target_routes})
        payload = {
            "server_id": route.server_id,
            "server_role": route.role,
            "server_branch": route.branch,
            "server_revision": route.revision,
            "server_endpoint": endpoint,
            "server_host": host,
            "online": route.online if online is None else bool(online),
            "ports": sorted({
                int(value) for value in (ports or target_ports or [route.port])
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
                for item in sorted(
                    target_routes,
                    key=lambda item: (item.port, item.branch),
                )
            ],
            "frequencies": list(source.get("frequencies") or []),
            "catalog_product_count": int(
                source.get("catalog_product_count") or 0
            ),
            "available_product_count": int(
                source.get("available_product_count") or 0
            ),
            "capability_revision": str(source.get("revision") or ""),
        }

    def federated_source_descriptors(
        self, *, refresh: bool = False,
    ) -> list[dict[str, object]]:
        """Merge local and peer source catalogs with provider metadata."""
        local_ports = self.local_service_routes(include_offline=True)
        peer_routes = self.federation_registry.routes(include_offline=True)
        if not local_ports and not peer_routes:
            # A Manager without an attached execution service is still useful
            # for catalog authoring.  Preserve the old projection contract in
            # that mode instead of fabricating a provider on port 7998.
            return [
                dict(item) for item in (self.client_state.product_sources() or [])
                if isinstance(item, dict)
            ]
        local_snapshot = self.local_capability_snapshot({"summary": True})
        local_by_id = {
            str(item.get("id") or ""): dict(item)
            for item in (self.client_state.product_sources() or [])
            if isinstance(item, dict) and str(item.get("id") or "")
        }
        summary_by_id = {
            str(item.get("id") or ""): item
            for item in (local_snapshot.get("sources") or [])
            if isinstance(item, dict) and str(item.get("id") or "")
        }
        merged: dict[str, dict[str, object]] = {}
        local_reference = (
            str(os.environ.get("FACTORTESTER_MANAGER_PUBLIC_ENDPOINT") or "")
            .strip().rstrip("/")
            or "http://127.0.0.1:7998"
        )
        local_route = ServiceRoute(
            server_id=self.server_id,
            role=self.server_role,
            branch=self.fixed_branch,
            revision=self._revision_for_path(),
            port=7998,
            endpoint=local_reference,
            online=True,
            latency_ms=0.0,
        )
        local_ports_values = [route.port for route in local_ports]
        for source_id, summary in summary_by_id.items():
            base = dict(local_by_id.get(source_id) or summary)
            base.setdefault("source_ref", f"data-source:server:{source_id}")
            base.setdefault("bundle_id", source_id)
            base.setdefault("bundle_name", base.get("source_name") or source_id)
            base["server_providers"] = [self._source_provider(
                local_route,
                source=summary,
                ports=local_ports_values or [7998],
                routes=local_ports or [local_route],
                online=any(route.online for route in local_ports) if local_ports else True,
            )]
            merged[source_id] = base

        peer_route_groups: dict[str, list[ServiceRoute]] = {}
        for route in peer_routes:
            peer_route_groups.setdefault(route.server_id, []).append(route)
        for server_id, routes in peer_route_groups.items():
            route = min(routes, key=self.route_selection_key)
            peer_snapshot = self._cached_peer_capabilities(
                route, refresh=refresh,
            )
            peer_sources = {
                str(item.get("id") or ""): item
                for item in ((peer_snapshot or {}).get("sources") or [])
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
                    for key in (
                        "provider_kind", "members", "frequencies",
                        "availability", "catalog_product_count",
                    ):
                        if key in summary:
                            base[key] = summary[key]
                base.setdefault("server_providers", []).append(
                    self._source_provider(
                        route,
                        source=summary,
                        routes=routes,
                        online=any(item.online for item in routes),
                    )
                )
            if not peer_sources:
                # Keep a visible provider row for an offline/degraded peer
                # when its last capability response is unavailable.  It is
                # useful in the overlay even though no source claim is made.
                continue
        for source in merged.values():
            providers = source.get("server_providers") or []
            source["server_providers"] = sorted(
                providers,
                key=lambda item: (
                    not bool(item.get("online")),
                    str(item.get("server_id") or ""),
                ),
            )
            source["server_provided"] = any(
                bool(item.get("online")) for item in providers
            )
        return sorted(
            merged.values(),
            key=lambda item: str(item.get("source_name") or item.get("id") or ""),
        )

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
            and not server_id
            and not branch
            and not feature
            and int(port) in self.service_ports()
        ):
            return self._local_route(port=int(port), online=True)

        if server_id or port is not None or branch or feature:
            return self.federation_registry.find(
                server_id=server_id,
                port=port,
                branch=branch,
                feature=feature,
                online_only=True,
            )

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
        raise TargetNotFound("no online service target")

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

    def registration_payload(
        self,
        endpoint: str,
        *,
        artifact_endpoint: str = "",
        ports: tuple[int, ...] | list[int] | set[int] | None = None,
    ) -> dict[str, object]:
        routes = self.local_service_routes(include_offline=True)
        online_ports = {
            route.port for route in routes if route.online
        }
        if ports is not None:
            # Preserve configured attachment ports, while also advertising
            # every service that is currently online.  New issue worktrees
            # therefore become visible without editing a hard-coded list.
            online_ports.update(int(value) for value in ports)
        routes = [
            route for route in routes
            if route.port in online_ports and route.online
        ]
        advertised_artifact_endpoint = (
            str(artifact_endpoint or "").strip().rstrip("/")
        )
        if advertised_artifact_endpoint:
            parsed_artifact_endpoint = urlparse(advertised_artifact_endpoint)
            if (
                parsed_artifact_endpoint.scheme not in {"http", "https"}
                or not parsed_artifact_endpoint.netloc
                or parsed_artifact_endpoint.username
                or parsed_artifact_endpoint.password
            ):
                raise ValueError(
                    "artifact_endpoint must be an http or https URL without credentials"
                )
        else:
            advertised_artifact_endpoint = artifact_data_endpoint(
                endpoint=endpoint,
                port=artifact_data_port(),
            )
        payload = {
            "schema_version": 1,
            "server_id": self.server_id,
            "role": self.server_role,
            "branch": self.fixed_branch or (routes[0].branch if routes else ""),
            "revision": self._revision_for_path(),
            "features": list(self.server_features),
            "endpoint": str(endpoint).rstrip("/"),
            "artifact_endpoint": advertised_artifact_endpoint,
            "artifact_port": artifact_data_port(),
            "proxy_token": self.federation_proxy_token(),
            "load": self.local_server_load(routes),
            "latency_ms": self.federation_peer_latency_ms,
            "ports": [
                {
                    "port": route.port,
                    "branch": route.branch,
                    "revision": route.revision,
                    "features": list(route.features),
                    "online": route.online,
                    "load": {
                        "load": route.load,
                        "active_jobs": route.active_jobs,
                        "queue_depth": route.queue_depth,
                    },
                }
                for route in routes
            ],
        }
        if self._transfer_server_endpoints is not None:
            payload["transfer_node"] = self.transfer_node_advertisement()
        return payload

    @staticmethod
    def local_server_load(routes: list[ServiceRoute]) -> dict[str, object]:
        return {
            "load": float(sum(route.load for route in routes)),
            "active_jobs": sum(route.active_jobs for route in routes),
            "queue_depth": sum(route.queue_depth for route in routes),
        }

    def advertised_federation_ports(self) -> tuple[int, ...]:
        """Return the currently online service ports for peer discovery."""
        return tuple(sorted(
            route.port
            for route in self.local_service_routes(include_offline=False)
            if route.online
        ))

    def peer_registration_payload(
        self,
        endpoint: str,
        *,
        artifact_endpoint: str = "",
    ) -> dict[str, object]:
        ports = self.advertised_federation_ports()
        return self.registration_payload(
            endpoint,
            artifact_endpoint=artifact_endpoint,
            ports=ports,
        )

    def accept_peer_registration(self, response: dict[str, object]) -> None:
        """Remember the peer returned by the authenticated registration call."""
        try:
            self.federation_peer_latency_ms = max(
                0.0, float(response.get("_roundtrip_ms") or 0.0),
            )
        except (TypeError, ValueError):
            self.federation_peer_latency_ms = None
        peer = response.get("peer")
        if not isinstance(peer, dict):
            return
        if self.federation_peer_latency_ms is not None:
            peer = {
                **peer,
                "latency_ms": self.federation_peer_latency_ms,
            }
        try:
            self.federation_registry.register(peer)
        except (TypeError, ValueError) as exc:
            print(f"[federation] peer registration was invalid: {exc}", flush=True)
            return
        advertisement = peer.get("transfer_node")
        if isinstance(advertisement, dict):
            try:
                self.accept_transfer_node_advertisement(advertisement)
            except (TypeError, ValueError) as exc:
                print(
                    f"[federation] peer transfer endpoints were invalid: {exc}",
                    flush=True,
                )
        # A peer heartbeat only updates service discovery.  Task summaries are
        # fetched on demand from the cross-server task-list tab.

    def start_federation_announcer(
        self,
        *,
        register_url: str,
        registration_token: str,
        endpoint: str,
        artifact_endpoint: str = "",
        ports: tuple[int, ...] | list[int] | set[int] | None = None,
        interval: float = 10.0,
    ) -> None:
        if self.federation_announcer is not None:
            return
        self.federation_sync.set_interval(interval)
        selected_ports = (
            None
            if ports is None
            else tuple(sorted({int(value) for value in ports}))
        )
        self.federation_announcer = FederationAnnouncer(
            register_url=register_url,
            registration_token=registration_token,
            payload_factory=lambda: self.registration_payload(
                endpoint,
                artifact_endpoint=artifact_endpoint,
                ports=selected_ports,
            ),
            response_handler=self.accept_peer_registration,
            transport=self.federation_gateway.transport,
            interval=interval,
        )
        self.federation_announcer.start()
        # Do not start a background task projection worker for every attach.

    def stop_federation_announcer(self) -> None:
        announcer = self.federation_announcer
        self.federation_announcer = None
        if announcer is not None:
            announcer.stop()

    def start_federation_sync(self) -> None:
        """Start event synchronization over the existing 7998 control plane."""
        self.federation_sync.start()

    def stop_federation_sync(self) -> None:
        self.federation_sync.stop()

    def sync_federation_once(self) -> list[dict[str, object]]:
        """Run one synchronous control-event pull for an admin/manual action."""
        return self.federation_sync.sync_once()

    def federation_config(self, *, public: bool = False) -> dict[str, object]:
        value = self.federation_config_store.load()
        return (
            self.federation_config_store.public(value)
            if public else value
        )

    def federation_config_status(self) -> dict[str, object]:
        value = self.federation_config()
        selected = {int(item) for item in value.get("ports") or []}
        available = self.local_service_routes(include_offline=True)
        targets = [
            {
                **route.as_dict(),
                "selected": route.port in selected,
            }
            for route in available
        ]
        return {
            "enabled": bool(value.get("enabled")),
            "active": self.federation_announcer is not None,
            "sync": self.federation_sync.status(),
            "role": self.server_role,
            "server_id": self.server_id,
            "targets": targets,
        }

    def public_device_targets(self) -> list[dict[str, object]]:
        """Compatibility seam for the Manager's public target projection."""
        return public_manager_targets(
            self.federation_registry,
            source_server_id=self.server_id,
        )

    @staticmethod
    def local_internal_addresses() -> list[str]:
        """Compatibility seam for server-provided local address discovery."""
        return local_internal_addresses()

    def server_network_info(self, *, request_endpoint: str = "") -> dict[str, object]:
        """Compatibility seam for the server-provided network projection."""
        return build_server_network_info(
            registry=self.federation_registry,
            federation_config=self.federation_config(),
            source_server_id=self.server_id,
            server_role=self.server_role,
            public_server=self.public_server,
            request_endpoint=request_endpoint,
        )

    def update_federation_config(self, payload: dict[str, object]) -> dict[str, object]:
        candidate = self.federation_config_store.merged(payload)
        enabled = bool(candidate.get("enabled"))
        selected = {int(item) for item in candidate.get("ports") or []}
        available = {
            route.port for route in self.local_service_routes(include_offline=True)
        }
        unknown = sorted(selected - available)
        if unknown:
            raise ValueError(
                "selected service port is not owned by this Manager: "
                + ", ".join(str(item) for item in unknown)
            )
        if enabled:
            for field in ("register_url", "public_endpoint", "registration_token"):
                if not str(candidate.get(field) or "").strip():
                    raise ValueError(f"{field} is required when attachment is enabled")
        self.stop_federation_announcer()
        self.stop_federation_sync()
        saved = self.federation_config_store.save(candidate)
        if enabled:
            self.start_federation_announcer(
                register_url=str(saved["register_url"]),
                registration_token=str(saved["registration_token"]),
                endpoint=str(saved["public_endpoint"]),
                artifact_endpoint=str(saved.get("artifact_endpoint") or ""),
                # An empty selection means automatic discovery: every service
                # port that is online at heartbeat time is advertised.  The
                # announcer keeps this list dynamic instead of pinning one
                # issue worktree such as 8141.
                ports=tuple(sorted(selected)),
                interval=float(saved["interval"]),
            )
        return {
            "config": self.federation_config(public=True),
            "status": self.federation_config_status(),
        }

    def start_configured_federation(self) -> None:
        value = self.federation_config()
        if not bool(value.get("enabled")):
            return
        try:
            self.update_federation_config({})
        except (OSError, TypeError, ValueError) as exc:
            print(f"[federation] configured attachment is unavailable: {exc}", flush=True)

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
