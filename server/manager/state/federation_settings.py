"""Federation attachment settings and network projections."""

from __future__ import annotations

from server.manager.services.network_info import (
    local_internal_addresses,
    public_manager_targets,
    server_network_info as build_server_network_info,
)


class FederationSettingsStateMixin:
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
            manager_public_endpoint=str(
                getattr(self, "manager_public_endpoint", "") or ""
            ),
            managed_organizations=self.managed_organizations,
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
            for field in (
                "bootstrap_url", "public_endpoint", "registration_token",
            ):
                if not str(candidate.get(field) or "").strip():
                    raise ValueError(f"{field} is required when attachment is enabled")
        self.stop_federation_announcer()
        self.stop_federation_sync()
        saved = self.federation_config_store.save(candidate)
        if enabled:
            self.start_federation_announcer(
                bootstrap_url=str(saved["bootstrap_url"]),
                registration_token=str(saved["registration_token"]),
                endpoint=str(saved["public_endpoint"]),
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
            print(f"[federation] configured bootstrap is unavailable: {exc}", flush=True)
