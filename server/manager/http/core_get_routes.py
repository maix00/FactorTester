"""Top-level GET dispatch, static assets, sessions, and Manager shell."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse

from server.manager.config import VIBE_TRADING_PORT
from server.manager.domain.navigation_registry import navigation_modules
from server.manager.http.localization import web_localization
from server.manager.http.responses import json_response
from server.manager.web.assets import asset_revision, shell_bytes, static_file


class CoreGetRoutesMixin:
    """Order focused GET route families without owning their implementations."""

    def _get_entry_routes(self, parsed) -> bool:
        if parsed.path in {"/favicon.svg", "/favicon.ico"}:
            return self._serve_site_icon()
        if parsed.path == "/compliance":
            requested = parse_qs(parsed.query, keep_blank_values=True).get(
                "next", ["/"]
            )[0]
            requested = str(requested or "/")
            if self._redirect_configured_ingress(
                parsed,
                next_path=requested,
            ):
                return True
            visitor_grant = parse_qs(
                parsed.query,
                keep_blank_values=True,
            ).get("grant", [""])[0]
            self._serve_compliance_page(
                requested,
                visitor_grant=str(visitor_grant or ""),
            )
            return True
        if parsed.path == "/visitor":
            self._serve_visitor_entry(parsed)
            return True
        if parsed.path == "/login":
            requested = parse_qs(parsed.query, keep_blank_values=True).get(
                "next", ["/"]
            )[0]
            if self._redirect_configured_ingress(
                parsed,
                next_path=str(requested or "/"),
            ):
                return True
            self._serve_login_page(parsed)
            return True
        if not self._public_login_gate(parsed, method="GET"):
            return True
        if self._mihomo_get(parsed):
            return True
        if self._get_transfer_metrics(parsed):
            return True
        if parsed.path == "/api/devices":
            self._device_list()
            return True
        if parsed.path == "/api/admin/access-control":
            self._admin_access_control()
            return True
        if parsed.path == "/api/admin/account-directory":
            self._admin_account_directory()
            return True
        if parsed.path == "/api/device/summary":
            self._device_summary()
            return True
        if parsed.path == "/api/server/network-info":
            self._server_network_info()
            return True
        if parsed.path == "/api/federation/servers":
            self._federation_servers()
            return True
        if parsed.path == "/api/federation/config":
            self._federation_config()
            return True
        if parsed.path == "/api/control-database/config":
            self._control_database_config()
            return True
        if parsed.path == "/api/client-assets/revision":
            json_response(
                self,
                {"success": True, "revision": asset_revision()},
                headers={"Cache-Control": "no-store"},
            )
            return True
        locale_match = re.fullmatch(
            r"/api/localizations/(zh-Hans|en)", parsed.path,
        )
        if locale_match:
            try:
                value = web_localization(
                    self.state.runtime_source_root
                    / "apple/Resources/Shared/Localizable.xcstrings",
                    locale_match.group(1),
                )
            except (OSError, ValueError, json.JSONDecodeError):
                json_response(self, {"success": False, "error": "localization catalog is unavailable"}, 503)
                return True
            json_response(self, value)
            return True
        if parsed.path.startswith("/research-static/"):
            try:
                body, content_type = static_file(
                    parsed.path.removeprefix("/research-static/"),
                )
            except ValueError:
                self.send_error(404)
                return True
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("X-Content-Type-Options", "nosniff")
            # The shell and module manifest are deliberately revalidated so a
            # worktree change is visible without restarting Manager.  Every
            # versioned module/style URL carries the asset revision from that
            # manifest, so keeping those immutable is safe and avoids
            # downloading and reparsing the same lazy code on every route.
            relative = parsed.path.removeprefix("/research-static/")
            if relative in {"", "research.html", "module-manifest.json"}:
                self.send_header("Cache-Control", "no-store")
            else:
                self.send_header(
                    "Cache-Control", "public, max-age=31536000, immutable",
                )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        if parsed.path == "/static/config/modules.json":
            try:
                body = (
                    self.state.runtime_source_root
                    / "static/config/modules.json"
                ).read_bytes()
                json.loads(body.decode("utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                json_response(
                    self,
                    {"success": False, "error": "module manifest is unavailable"},
                    503,
                )
                return True
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        if self._serve_client_release(parsed.path):
            return True
        if parsed.path == "/api/modules":
            session = self._session()
            json_response(self, {
                "version": 2,
                "modules": navigation_modules(session),
            })
            return True
        if parsed.path == "/profiles":
            self.send_response(302)
            self.send_header("Location", "/research?section=profiles")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return True
        return False

    def _serve_site_icon(self) -> bool:
        try:
            body = (
                self.state.runtime_source_root / "static/favicon.svg"
            ).read_bytes()
        except OSError:
            self.send_error(404)
            return True
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

    def _get_session_and_shell_routes(self, parsed) -> bool:
        if self._get_manager_identity_route(parsed):
            return True
        if parsed.path == "/api/session":
            session = self.state.session(self._bearer_token())
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            json_response(self, {"success": True, **session})
            return True
        if parsed.path == "/api/worktrees":
            if not self._has_api_authorization():
                self._require_capability()
                return True
            data = [
                {
                    "instance_id": self.state.instance_id(wt),
                    "label": wt.label,
                    "branch": wt.branch,
                    "head": wt.head,
                    "port": wt.port,
                    "running": self.state.is_running(wt.path),
                    "daemon_running": self.state.daemon_running(wt.path),
                    "port_in_use": self._runtime_port_in_use(wt.port),
                }
                for wt in self.state.worktrees()
            ]
            json_response(self, {
                "worktrees": data,
                "manager": {
                    "loopback_ip": "127.0.0.1",
                    "lan_ip": self._runtime_lan_ip(),
                    "release_root": str(self.state.release_root),
                },
                "vibe_trading": {
                    "instance_id": "service-vibe-trading",
                    "port": VIBE_TRADING_PORT,
                    "running": self.state.vibe_running(),
                    "port_in_use": self._runtime_port_in_use(
                        VIBE_TRADING_PORT,
                    ),
                },
            })
            return True
        shell_paths = {
            "/", "/research", "/jobs", "/factors", "/products",
            "/profiles", "/settings", "/manager", "/research-graphs",
            "/ic-test", "/backtest", "/test-templates", "/sqlite-web",
            "/sqlite-web/", "/mihomo", "/docs",
        }
        if (
            parsed.path in shell_paths
            or parsed.path.startswith("/research/")
            or parsed.path.startswith("/jobs/")
            or parsed.path.startswith("/factors/")
            or parsed.path.startswith("/products/")
            or parsed.path.startswith("/profiles/")
            or parsed.path.startswith("/settings/")
            or parsed.path.startswith("/research-graphs/")
            or parsed.path.startswith("/ic-test/")
            or parsed.path.startswith("/backtest/")
            or parsed.path.startswith("/test-templates/")
            or parsed.path.startswith("/docs/")
        ):
            body = shell_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            # Artifact previews are fetched as authenticated blobs before they
            # are assigned to an <img>.  Keep the shell same-origin-only while
            # explicitly permitting those object URLs; without this WebKit
            # silently reports the preview as unreadable even though /preview
            # returned a valid image.
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' blob: data: https:; "
                "style-src 'self' 'unsafe-inline'; "
                "script-src 'self' https://cdn.platform.openai.com; "
                "frame-src 'self' https://cdn.platform.openai.com; "
                "connect-src 'self' http: https:",
            )
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        return False

    def do_GET(self) -> None:
        if self._redirect_plain_http_to_https():
            return
        parsed = urlparse(self.path)
        handlers = (
            self._get_entry_routes,
            self._get_technical_docs_routes,
            self._get_transfer_access_status,
            self._get_job_list_routes,
            self._get_agent_app_routes,
            self._get_agent_routes,
            self._get_server_research_routes,
            self._get_client_research_routes,
            self._get_public_research_routes,
            self._get_session_and_shell_routes,
            self._proxy_service_get,
        )
        for handler in handlers:
            if handler(parsed):
                return
        self.send_error(404)

    def do_HEAD(self) -> None:  # noqa: N802
        """Serve bodyless release metadata needed by Sparkle downloads."""
        if self._redirect_plain_http_to_https():
            return
        parsed = urlparse(self.path)
        if self._serve_client_release(parsed.path):
            return
        self.send_error(404)
