"""Runtime reconfiguration boundary for the authoritative control database."""

from __future__ import annotations

from server.manager.storage.control_db import PostgresControlStore


class ControlDatabaseStateMixin:
    control_database_settings: object
    control_store: PostgresControlStore | None

    def control_database_status(self) -> dict[str, object]:
        return self.control_database_settings.status()

    def update_control_database(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        config = self.control_database_settings.candidate(payload)
        candidate = PostgresControlStore(config)
        # Verify credentials, network policy, TLS mode, and schema before the
        # new secret replaces a working configuration.
        candidate.load_accounts()
        self.control_database_settings.save(config)
        self.control_store = candidate
        self.device_registry.control_store = candidate
        self.device_authorizations.control_store = candidate
        return {
            **self.control_database_settings.status(),
            "healthy": True,
            "service_restart_required": bool(
                self.processes or self.data_plane_process
            ),
        }
