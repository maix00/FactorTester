"""Top-level GET dispatch, static assets, sessions, and Manager shell."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse

from server.manager.config import VIBE_TRADING_PORT
from server.manager.http.localization import web_localization
from server.manager.http.responses import json_response
from server.manager.web.assets import asset_revision, shell_bytes, static_file


class CoreGetRoutesMixin:
    """Order focused GET route families without owning their implementations."""

    def _get_entry_routes(self, parsed) -> bool:
        if parsed.path == "/compliance":
            requested = parse_qs(parsed.query, keep_blank_values=True).get(
                "next", ["/"]
            )[0]
            self._serve_compliance_page(str(requested or "/"))
            return True
        if parsed.path == "/login":
            self._serve_login_page(parsed)
            return True
        if parsed.path == "/device-authorize":
            if not self._public_login_gate(parsed, method="GET"):
                return True
            self._device_authorization_page(parsed)
            return True
        if not self._public_login_gate(parsed, method="GET"):
            return True
        if parsed.path == "/api/devices":
            self._device_list()
            return True
        if parsed.path == "/api/device/summary":
            self._device_summary()
            return True
        if parsed.path == "/api/device/public-targets":
            self._device_public_targets()
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
            # 7998 serves the web shell directly from the selected worktree.
            # Do not cache source assets: a changed JS/CSS file is visible on
            # the next navigation without restarting the manager process.
            self.send_header("Cache-Control", "no-store")
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
            manager = bool(
                session and session["capabilities"]["manager"]
            )
            modules = [
                {"id": "home", "title": "主页", "title_key": "主页", "icon": "grid", "sfSymbol": "square.grid.2x2"},
                {"id": "research", "title": "研究", "title_key": "研究", "icon": "chart", "sfSymbol": "chart.xyaxis.line"},
                {"id": "ic-test", "title": "IC 测试", "title_key": "IC 测试", "icon": "correlation", "sfSymbol": "chart.xyaxis.line"},
                {"id": "backtest", "title": "回测", "title_key": "回测", "icon": "backtest", "sfSymbol": "chart.line.uptrend.xyaxis"},
                {"id": "jobs", "title": "测试任务", "title_key": "测试任务", "icon": "checklist", "sfSymbol": "checklist"},
                {"id": "factors", "title": "因子库", "title_key": "因子库", "icon": "function", "sfSymbol": "function"},
                {"id": "products", "title": "产品", "title_key": "产品", "icon": "box", "sfSymbol": "shippingbox"},
                {"id": "profiles", "title": "Profiles", "title_key": "Profiles", "icon": "profiles", "sfSymbol": "person.2.crop.square.stack"},
                {"id": "sqlite_web", "title": "数据库", "title_key": "数据库", "icon": "SQL", "sfSymbol": "cylinder.split.1x2", "path": "/sqlite-web/", "requiresAuth": True, "homeOnly": True},
                {"id": "docs", "title": "技术文档", "title_key": "技术文档", "icon": "book", "sfSymbol": "book", "path": "/docs", "requiresAuth": False, "homeOnly": True},
                {"id": "settings", "title": "设置", "title_key": "设置", "icon": "settings", "sfSymbol": "person.crop.circle"},
            ]
            if manager:
                modules.append({
                    "id": "manager", "title": "服务器管理", "title_key": "服务器管理", "icon": "server", "sfSymbol": "server.rack", "homeOnly": True,
                })
            json_response(self, {"modules": modules})
            return True
        return False

    def _get_session_and_shell_routes(self, parsed) -> bool:
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
            "/sqlite-web/",
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
        ):
            body = shell_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            # Artifact previews are fetched as authenticated blobs before they
            # are assigned to an <img>.  Keep the shell same-origin-only while
            # explicitly permitting those object URLs; without this WebKit
            # silently reports the preview as unreadable even though /preview
            # returned a valid image.
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob: data: https:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        self.send_error(404)
        return True

    def do_GET(self) -> None:
        if self._redirect_plain_http_to_https():
            return
        parsed = urlparse(self.path)
        handlers = (
            self._get_entry_routes,
            self._get_job_list_routes,
            self._get_client_research_routes,
            self._get_public_research_routes,
            self._get_session_and_shell_routes,
        )
        for handler in handlers:
            if handler(parsed):
                return
        self.send_error(404)
