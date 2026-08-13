"""Semantic slice of the authenticated federation HTTP adapter."""

from __future__ import annotations

from server.manager.http.responses import json_response

class FederationAdminRoutesMixin:
    def _federation_servers(self) -> None:
        if not self._has_api_authorization():
            self._require_capability()
            return
        servers = []
        for item in self.state.federation_registry.servers(include_offline=True):
            servers.append({
                key: value
                for key, value in item.items()
                if key not in {"proxy_token"}
            })
        json_response(self, {
            "success": True,
            "server_id": self.state.server_id,
            "role": self.state.server_role,
            "local_targets": [
                route.as_dict()
                for route in self.state.local_service_routes(include_offline=False)
            ],
            "servers": servers,
        })

    def _has_super_admin_session(self) -> bool:
        session = self._session()
        return bool(
            self._has_secure_ui_transport()
            and session
            and str(session.get("role") or "") == "super_admin"
        )

    def _require_super_admin_session(self) -> bool:
        if self._has_super_admin_session():
            return True
        session = self._session()
        status = 401 if session is None else 403
        json_response(
            self,
            {
                "success": False,
                "error": "super administrator permission required",
            },
            status,
        )
        return False

    def _federation_config(self) -> None:
        if not self._require_super_admin_session():
            return
        json_response(self, {
            "success": True,
            "config": self.state.federation_config(public=True),
            "status": self.state.federation_config_status(),
            "available_ports": [
                route.as_dict()
                for route in self.state.local_service_routes(
                    include_offline=False,
                )
            ],
        })

    def _update_federation_config(self) -> None:
        if not self._require_super_admin_session():
            return
        try:
            value = self.state.update_federation_config(
                self._json_body(256 * 1024),
            )
        except (TypeError, ValueError, OSError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
