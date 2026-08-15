"""Protected Manager identity and server-owned access declarations."""

from __future__ import annotations

from server.manager.config import CLIENT_DATA_PORT
from server.manager.http.responses import json_response


class ManagerIdentityRoutesMixin:
    """Expose only the metadata a Manager client needs to identify a node."""

    def _get_manager_identity_route(self, parsed) -> bool:
        if parsed.path not in {"/api/manager/identity", "/api/manager/access"}:
            return False
        if not self._has_api_authorization():
            self._require_capability()
            return True

        data_plane = getattr(self.state, "data_plane_process_config", None)
        json_response(self, {
            "success": True,
            "server": {
                "server_id": str(getattr(self.state, "server_id", "") or ""),
                "role": str(getattr(self.state, "server_role", "") or ""),
                "public_server": bool(
                    getattr(self.state, "public_server", False)
                ),
                "managed_organizations": list(
                    getattr(self.state, "managed_organizations", ()) or ()
                ),
                "features": list(
                    getattr(self.state, "server_features", ()) or ()
                ),
            },
            "factor_tester": {
                "control_endpoint": str(
                    getattr(self.state, "manager_public_endpoint", "") or ""
                ),
                "data_endpoint": str(
                    getattr(data_plane, "client_data_endpoint", "") or ""
                ),
                "control_port": 7998,
                "data_port": int(
                    getattr(data_plane, "client_port", CLIENT_DATA_PORT)
                    or CLIENT_DATA_PORT
                ),
                "service_ports": sorted(
                    int(port) for port in self.state.service_ports()
                ),
            },
            # This is a server-owned declaration loaded from .settings.  It
            # contains no credentials and is intentionally not interpreted by
            # the Manager CLI as an executable instruction.
            "management_access": [
                dict(item)
                for item in getattr(self.state, "management_access", ())
            ],
        })
        return True


__all__ = ["ManagerIdentityRoutesMixin"]
