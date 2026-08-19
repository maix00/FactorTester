"""Node registration, signed discovery, and lazy direct authentication."""

from __future__ import annotations

import time

from server.manager.domain.federation import (
    FederationAnnouncer,
    ServiceRoute,
    TargetNotFound,
    TargetUnavailable,
)
from server.manager.network_endpoints import validate_client_endpoint
from server.manager.services.host_lan_runtime import (
    dynamic_host_client_endpoints,
)
from server.manager.services.network_info import local_internal_addresses


class FederationMembershipStateMixin:
    def registration_payload(
        self,
        endpoint: str,
        *,
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
        selected_endpoint = self._refresh_host_client_endpoints(endpoint)
        payload = {
            "schema_version": 1,
            "server_id": self.server_id,
            "role": self.server_role,
            "public_server": bool(self.public_server),
            "managed_organizations": list(self.managed_organizations),
            "internal_addresses": (
                [] if self.public_server else local_internal_addresses()
            ),
            "branch": self.fixed_branch or (routes[0].branch if routes else ""),
            "revision": self._revision_for_path(),
            "features": list(self.server_features),
            "endpoint": selected_endpoint,
            "proxy_token": self.federation_proxy_token(),
            "load": self.local_server_load(routes),
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

    def _refresh_host_client_endpoints(self, endpoint: str) -> str:
        """Replace container client endpoints with the current host LAN IP."""
        current = self._transfer_server_endpoints
        if self.public_server:
            return self._federation_client_endpoint(endpoint)
        selected = dynamic_host_client_endpoints(current)
        if selected is None:
            return self._federation_client_endpoint(endpoint)
        if selected != current:
            self.configure_transfer_endpoints(selected)
        return selected.client_control_endpoint

    def _federation_client_endpoint(self, endpoint: str = "") -> str:
        """Return the signed public endpoint owned by this node.

        Port 17998 is an overlay-only listener.  A request's ``Host`` header
        therefore must never be promoted to the client-facing Manager URL.
        """
        supplied = str(endpoint or "").strip().rstrip("/")
        configured = (
            self._transfer_server_endpoints.client_control_endpoint
            if self._transfer_server_endpoints is not None
            else ""
        )
        if supplied:
            supplied = validate_client_endpoint(
                supplied,
                name="federation client control endpoint",
            )
        if configured and supplied and configured != supplied:
            raise ValueError(
                "federation endpoint does not match signed client endpoint"
            )
        selected = configured or supplied
        if not selected:
            raise ValueError("federation client control endpoint is required")
        return selected

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

    def federation_registration_payload(
        self,
        endpoint: str = "",
    ) -> dict[str, object]:
        ports = self.advertised_federation_ports()
        return self.registration_payload(
            endpoint,
            ports=ports,
        )

    def peer_registration_payload(
        self,
        endpoint: str,
    ) -> dict[str, object]:
        """Compatibility alias for schema-v1 two-node callers."""
        return self.federation_registration_payload(endpoint)

    def accept_federation_registration(
        self,
        payload: dict[str, object],
        *,
        observed_latency_ms: float | None = None,
        now: float | None = None,
    ) -> dict[str, object]:
        """Verify and install one directly authenticated node registration."""
        candidate = self.federation_registry.validate(payload)
        server_id = str(candidate["server_id"])
        if server_id == self.server_id:
            raise ValueError("a federated node cannot register itself")
        advertisement = payload.get("transfer_node")
        if not isinstance(advertisement, dict):
            raise ValueError("transfer node advertisement is required")
        current = time.time() if now is None else float(now)
        verified, endpoints = self.validate_transfer_node_advertisement(
            advertisement,
            expected_node_id=server_id,
            now=current,
        )
        if str(candidate["endpoint"]) != endpoints.client_control_endpoint:
            raise ValueError(
                "federation endpoint does not match signed client endpoint"
            )
        if observed_latency_ms is None:
            candidate["latency_ms"] = None
        else:
            candidate["latency_ms"] = max(0.0, float(observed_latency_ms))
        # Install the replay-protected signed identity before making the
        # service route visible.  A stale/replayed advertisement can never
        # refresh the route lease.
        self.install_transfer_node_advertisement(
            verified,
            endpoints,
            now=current,
        )
        return self.federation_registry.register(candidate)

    def _catalog_registration_url(
        self,
        candidate: dict[str, object],
        *,
        now: float,
    ) -> tuple[str, float]:
        """Verify one credential-free directory entry without installing it."""
        if "proxy_token" in candidate:
            raise ValueError("federation directory must not contain credentials")
        node_id = str(candidate.get("server_id") or "").strip()
        if not node_id:
            raise ValueError("federation directory server_id is required")
        advertisement = candidate.get("transfer_node")
        if not isinstance(advertisement, dict):
            raise ValueError("transfer node advertisement is required")
        verified, endpoints = self.validate_transfer_node_advertisement(
            advertisement,
            expected_node_id=node_id,
            now=now,
        )
        return (
            endpoints.peer_control_endpoint.rstrip("/")
            + "/api/federation/register",
            verified.expires_at,
        )

    def _remember_federation_directory_entry(
        self,
        candidate: dict[str, object],
        *,
        registration_url: str,
        expires_at: float,
    ) -> None:
        node_id = str(candidate.get("server_id") or "").strip()
        self.federation_directory.remember(
            candidate,
            registration_url=registration_url,
            expires_at=expires_at,
        )

    def federation_discovered_nodes(
        self,
        *,
        now: float | None = None,
    ) -> list[dict[str, object]]:
        """Return credential-free nodes known through signed discovery."""
        result = []
        for node in self.federation_directory.nodes(now=now):
            node_id = str(node.get("server_id") or "")
            result.append({
                **node,
                "authenticated": (
                    self.federation_registry.describe(node_id) is not None
                ),
            })
        return sorted(result, key=lambda item: str(item.get("server_id") or ""))

    def activate_federated_node(self, server_id: str) -> None:
        """Establish a direct authenticated relationship on first use."""
        selected = str(server_id or "").strip()
        try:
            registration_url = self.federation_directory.registration_url(
                selected,
            )
        except KeyError:
            raise TargetNotFound(f"federated node {selected or '<empty>'} was not discovered")
        announcer = self.federation_announcer
        if announcer is None:
            raise TargetUnavailable("federation attachment is not active")
        try:
            announcer.activate(
                selected,
                registration_url,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise TargetUnavailable(
                f"federated node {selected} direct registration failed: {exc}"
            ) from exc
        if self.federation_registry.describe(selected) is None:
            raise TargetUnavailable(
                f"federated node {selected} did not establish a direct route"
            )

    def accept_federation_catalog(
        self,
        response: dict[str, object],
    ) -> tuple[str, ...]:
        """Merge a bootstrap response into this node's federated directory.

        ``peer`` remains accepted for the two-node v1 response.  The canonical
        response is ``nodes``: a set keyed by stable ``server_id``.  Only the
        responding bootstrap receives this request's measured RTT; latency
        copied from another node would not describe a route from this node.
        """
        try:
            observed_latency_ms = max(
                0.0, float(response.get("_roundtrip_ms") or 0.0),
            )
        except (TypeError, ValueError):
            observed_latency_ms = None
        current = time.time()
        bootstrap_server_id = str(
            response.get("bootstrap_server_id") or ""
        ).strip()

        # Only the direct responder may carry a routing credential.  Verify
        # its signed identity and endpoint before refreshing its route lease.
        peer = response.get("peer")
        if isinstance(peer, dict):
            peer_id = str(peer.get("server_id") or "").strip()
            if bootstrap_server_id and peer_id != bootstrap_server_id:
                raise ValueError(
                    "bootstrap server_id does not match direct peer"
                )
            try:
                self.accept_federation_registration(
                    peer,
                    observed_latency_ms=observed_latency_ms,
                    now=current,
                )
            except PermissionError as exc:
                # Replaying an already processed response is harmless, but it
                # must not refresh the route lease.
                if "replay" not in str(exc).lower() and "stale" not in str(exc).lower():
                    raise

        raw_nodes = response.get("nodes")
        if not isinstance(raw_nodes, list):
            return ()
        registration_urls: set[str] = set()
        for candidate in raw_nodes:
            if not isinstance(candidate, dict):
                continue
            node_id = str(candidate.get("server_id") or "").strip()
            if node_id in {"", self.server_id, bootstrap_server_id}:
                continue
            try:
                registration_url, expires_at = self._catalog_registration_url(
                    candidate,
                    now=current,
                )
                self._remember_federation_directory_entry(
                    candidate,
                    registration_url=registration_url,
                    expires_at=expires_at,
                )
                registration_urls.add(registration_url)
            except (PermissionError, TypeError, ValueError) as exc:
                print(
                    f"[federation] directory entry was invalid: {exc}",
                    flush=True,
                )
        return tuple(sorted(registration_urls))

    def accept_peer_registration(
        self,
        response: dict[str, object],
    ) -> tuple[str, ...]:
        """Compatibility alias for schema-v1 two-node callers."""
        return self.accept_federation_catalog(response)
        # A peer heartbeat only updates service discovery.  Task summaries are
        # fetched on demand from the cross-server task-list tab.

    def start_federation_announcer(
        self,
        *,
        bootstrap_url: str,
        registration_token: str,
        endpoint: str,
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
            bootstrap_url=bootstrap_url,
            registration_token=registration_token,
            payload_factory=lambda: self.registration_payload(
                endpoint,
                ports=selected_ports,
            ),
            response_handler=self.accept_federation_catalog,
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
