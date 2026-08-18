"""Super-admin entry, status, and same-origin bridge for Mihomo Dashboard."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import urlparse

from server.manager.http.mihomo_proxy import (
    MihomoProxyError,
    forward_http,
    forward_websocket,
)
from server.manager.http.responses import json_response
from server.manager.services.mihomo_supervisor import MihomoError


class MihomoDashboardRoutesMixin:
    """Keep the third-party dashboard behind the existing Manager session."""

    _MIHOMO_DASHBOARD_PREFIX = "/mihomo-dashboard"
    _MIHOMO_API_PREFIX = "/mihomo-api"

    def _mihomo_get(self, parsed) -> bool:
        if parsed.path == "/api/admin/mihomo":
            if not self._require_super_admin_session():
                return True
            json_response(self, {
                "success": True,
                "mihomo": self.state.mihomo.status(),
            }, headers={"Cache-Control": "no-store"})
            return True
        if parsed.path == self._MIHOMO_DASHBOARD_PREFIX:
            if not self._require_super_admin_session():
                return True
            self.send_response(302)
            self.send_header("Location", self._MIHOMO_DASHBOARD_PREFIX + "/")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return True
        if parsed.path.startswith(self._MIHOMO_DASHBOARD_PREFIX + "/"):
            if not self._require_super_admin_session():
                return True
            return self._serve_mihomo_dashboard(parsed.path)
        if parsed.path == self._MIHOMO_API_PREFIX or parsed.path.startswith(
            self._MIHOMO_API_PREFIX + "/"
        ):
            if not self._require_super_admin_session():
                return True
            return self._proxy_mihomo(parsed, "GET")
        return False

    def _mihomo_write(self, parsed, method: str) -> bool:
        if parsed.path == "/api/admin/mihomo":
            if not self._require_super_admin_session():
                return True
            try:
                payload = self._json_body(16 * 1024)
                action = str(payload.get("action") or "").strip().lower()
                if action == "start":
                    value = self.state.mihomo.start()
                elif action == "stop":
                    value = self.state.mihomo.stop()
                elif action == "restart":
                    value = self.state.mihomo.restart()
                else:
                    raise ValueError("unsupported Mihomo action")
            except (TypeError, ValueError, MihomoError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
                return True
            json_response(self, {
                "success": not bool(value.get("last_error")),
                "mihomo": value,
            }, status=200 if not value.get("last_error") else 503)
            return True
        if not (
            parsed.path == self._MIHOMO_API_PREFIX
            or parsed.path.startswith(self._MIHOMO_API_PREFIX + "/")
        ):
            return False
        if not self._require_super_admin_session():
            return True
        return self._proxy_mihomo(parsed, method)

    def _proxy_mihomo(self, parsed, method: str) -> bool:
        target = parsed.path.removeprefix(self._MIHOMO_API_PREFIX) or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        target_path = urlparse(target).path or "/"
        if method != "GET" and not self._mihomo_write_allowed(method, target_path):
            json_response(
                self,
                {"success": False, "error": "Mihomo configuration writes are disabled"},
                403,
            )
            return True
        try:
            host, port = self.state.mihomo.api_endpoint()
            if self.headers.get("Upgrade", "").lower() == "websocket":
                forward_websocket(self, target, host, port)
            else:
                forward_http(self, target, method, host, port)
        except MihomoError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
        except MihomoProxyError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 502)
        return True

    @staticmethod
    def _mihomo_write_allowed(method: str, path: str) -> bool:
        if method == "DELETE":
            return path == "/connections" or path.startswith("/connections/")
        if method == "PUT":
            return path.startswith("/proxies/") and path != "/proxies/"
        return False

    def _serve_mihomo_dashboard(self, request_path: str) -> bool:
        root = (
            self.state.runtime_source_root
            / "server"
            / "manager"
            / "vendor"
            / "metacubexd"
        ).resolve()
        relative = request_path.removeprefix(self._MIHOMO_DASHBOARD_PREFIX + "/")
        relative = relative or "index.html"
        if relative == "config.js":
            body = (
                "window.__METACUBEXD_CONFIG__ = "
                "{ defaultBackendURL: '/mihomo-api', githubToken: '' };\n"
            ).encode("utf-8")
            content_type = "application/javascript"
        else:
            path = (root / relative).resolve()
            if root not in path.parents or not path.is_file():
                self.send_error(404)
                return True
            body = path.read_bytes()
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self' wss: https:; "
            "img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'; "
            "font-src 'self' data:; worker-src 'self' blob:",
        )
        self.send_header(
            "Cache-Control",
            "no-store" if relative in {"index.html", "config.js"}
            else "public, max-age=86400, immutable",
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True


__all__ = ["MihomoDashboardRoutesMixin"]
