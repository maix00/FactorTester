"""Protected Manager identity and server-owned access declarations."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import unquote

from server.manager.config import CLIENT_DATA_PORT
from server.manager.http.responses import json_response
from server.manager.services.server_access import management_access_script_path


class ManagerIdentityRoutesMixin:
    """Expose only the metadata a Manager client needs to identify a node."""

    def _get_manager_identity_route(self, parsed) -> bool:
        if re.fullmatch(
            r"/api/manager/access/[A-Za-z0-9._:-]{1,128}/script",
            unquote(parsed.path),
        ):
            self._manager_access_script(parsed)
            return True
        if parsed.path == "/api/manager/health":
            self._manager_health()
            return True
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

    def _manager_health(self) -> None:
        if not self._has_api_authorization():
            self._require_capability()
            return
        config = getattr(self.state, "data_plane_process_config", None)
        process = getattr(self.state, "data_plane_process", None)
        process_running = bool(process is not None and process.poll() is None)
        checks: dict[str, object] = {
            "manager": {"status": "ok"},
            "data_plane": {
                "configured": config is not None,
                "running": process_running,
                "client_port": int(
                    getattr(config, "client_port", CLIENT_DATA_PORT)
                    or CLIENT_DATA_PORT
                ),
            },
            "services": {
                "ports": sorted(int(port) for port in self.state.service_ports()),
            },
        }
        for name, callback in (
            ("control_database", getattr(self.state, "control_database_status", None)),
            ("federation", getattr(self.state, "federation_config_status", None)),
        ):
            if not callable(callback):
                checks[name] = {"status": "unavailable"}
                continue
            try:
                checks[name] = callback()
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                checks[name] = {"status": "error", "error": str(exc)}
        try:
            revision = self.state._revision_for_path()
        except (OSError, RuntimeError, TypeError, ValueError):
            revision = ""
        json_response(self, {
            "success": True,
            "server_id": str(getattr(self.state, "server_id", "") or ""),
            "role": str(getattr(self.state, "server_role", "") or ""),
            "revision": str(revision or ""),
            "checks": checks,
        }, headers={"Cache-Control": "no-store"})

    def _manager_access_script(self, parsed) -> None:
        if not self._has_api_authorization():
            self._require_capability()
            return
        match = re.fullmatch(
            r"/api/manager/access/([A-Za-z0-9._:-]{1,128})/script",
            unquote(parsed.path),
        )
        if match is None:
            self.send_error(404)
            return
        method_id = unquote(match.group(1))
        method = next(
            (
                item for item in getattr(self.state, "management_access", ())
                if str(item.get("id") or "") == method_id
            ),
            None,
        )
        script = method.get("script") if isinstance(method, dict) else None
        if not isinstance(script, dict):
            json_response(
                self,
                {"success": False, "error": "connection script is not declared"},
                404,
            )
            return
        try:
            path = management_access_script_path(
                self.state.repo, str(script.get("id") or ""),
            )
            body = path.read_bytes()
            if len(body) > 4 * 1024 * 1024:
                raise ValueError("connection script is too large")
            digest = hashlib.sha256(body).hexdigest()
            if digest != str(script.get("sha256") or "").lower():
                raise ValueError("connection script digest mismatch")
        except FileNotFoundError:
            json_response(
                self,
                {"success": False, "error": "connection script is unavailable"},
                404,
            )
            return
        except (OSError, ValueError) as exc:
            json_response(
                self,
                {"success": False, "error": str(exc)},
                503,
            )
            return
        filename = str(script.get("filename") or "connection.sh")
        content_type = str(script.get("content_type") or "text/x-shellscript")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header(
            "Content-Disposition", f'attachment; filename="{filename}"',
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", f'"{digest}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


__all__ = ["ManagerIdentityRoutesMixin"]
