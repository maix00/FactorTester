#!/usr/bin/env python3
"""FactorTester Manager runtime: state, services, and HTTP route dispatch.

Process configuration and listener lifecycle are intentionally kept in
``server.manager.app``.  This module is the implementation behind that
minimal bootstrap and remains import-compatible with the former
``scripts.worktree_flask_manager`` path during the server-package migration.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import ipaddress
import json
import os
import re
import secrets
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser  # compatibility export for the former script module
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urlencode, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from server.manager.web.assets import asset_revision, shell_bytes, static_file
from server.manager.config import (
    ARTIFACT_DATA_PORT,
    FEAT_PORT,
    MAIN_PORT,
    MANAGER_SESSION_REFRESH_WINDOW_SECONDS,
    MANAGER_SESSION_TTL_SECONDS,
    VIBE_TRADING_PORT,
)
from server.manager.http.gateway import GatewayResponse, ServiceGateway
from server.manager.http.device_routes import DeviceNetworkRoutesMixin
from server.manager.http.responses import json_response
from server.manager.services.client_state import ClientStateService
from server.manager.services.network_info import (
    local_internal_addresses,
    public_manager_targets,
    server_network_info as build_server_network_info,
)
from server.manager.domain.capabilities import capability_snapshot
from server.manager.domain.accounts import (
    account_role as _account_role,
    authenticate_user as _authenticate_user,
    manager_subordinate_users as _manager_subordinate_users,
)
from server.manager.http.localization import web_localization
from server.manager.storage.preferences import UserPreferenceStore
from server.manager.storage.job_index import ManagerJobIndex
from server.manager.storage.sqlite import ManagerSQLiteWeb, ManagerSQLiteResponse
from server.manager.domain.federation import (
    FederatedGateway,
    FederationConfigStore,
    FederatedServerRegistry,
    FederationAnnouncer,
    FederationSyncWorker,
    ServiceRoute,
    TargetNotFound,
    TargetUnavailable,
)
from server.jobs.artifact_data_plane import (
    ArtifactTicketCodec,
    ArtifactTicketError,
    artifact_data_endpoint,
    artifact_data_port,
    artifact_data_url,
)
from server.manager.services.test_authoring import (
    TestAuthoringError,
    TestAuthoringService,
)
from server.manager.http.pages import (
    PUBLIC_DEVICE_COMPLIANCE_NOTICE,
    PUBLIC_REGISTRATION_NOTICE,
    compliance_page as manager_compliance_page,
    login_page as manager_login_page,
    safe_login_next as manager_safe_login_next,
)
from server.manager.domain.devices import (
    DeviceChallengeStore,
    DeviceAuthorizationStore,
    DeviceRegistry,
)
from server.manager.storage.control_db import control_store_from_env
from server.manager.http.security import (
    configured_tls_paths,
    enable_server_tls,
    server_tls_context,
)
from server.manager.state.models import (
    ExternalProcess as _ExternalProcess,
    ServiceBundle,
    Worktree,
)
from server.manager.state.sessions import SessionStateMixin
from server.manager.state.routing import RoutingStateMixin
from server.manager.state.jobs import JobProjectionStateMixin
from server.manager.state.worktrees import WorktreeStateMixin
from server.manager.state.processes import ProcessStateMixin
from server.manager.system import (
    ISSUE_BRANCH_RE as _ISSUE_BRANCH_RE,
    extract_issue_number as _extract_issue_number,
    lan_ip as _lan_ip,
    port_in_use,
    safe_name,
    write_owner_only_once as _write_owner_only_once,
)
from tools.cli.release.research_reporting.public_research import (
    PublicResearchLibrary,
)
from server.services.client_release_channels import (
    load_beta_sparkle_appcast,
    load_client_release_channel,
)


VIBE_TRADING_ROOT = Path(
    os.environ.get(
        "VIBE_TRADING_ROOT",
        "/Users/maxdeux/Documents/Vibe-Trading-Integration",
    )
).expanduser()

_MANAGER_ACTION_PATHS = frozenset({
    "/vibe/start",
    "/vibe/stop",
    "/start",
    "/stop",
    "/restart-api",
    "/restart-bundle",
    "/force-stop",
})


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class IPv6LoopbackHTTPServer(ThreadingHTTPServer):
    """Serve the local manager on ``::1`` alongside its IPv4 listener.

    macOS may resolve ``localhost`` to IPv6 first.  The manager is deliberately
    kept loopback-only, so this companion listener fixes that resolution path
    without changing the service's LAN exposure or authentication boundary.
    """

    address_family = socket.AF_INET6
    allow_reuse_address = True

_SERVICE_GET_PREFIXES = (
    "/docs",
    "/static/css/",
    "/static/js/",
    "/static/vendor/",
    "/static/images/",
    "/custom-factors/api/client/factor-library",
    "/custom-factors/api/client/factor-sets",
    "/api/product-groups",
    "/api/report-references/validate",
    "/api/profile-research",
    "/api/research-graphs/",
    "/api/research-evidence/",
    "/api/trial-plans/direct/",
    "/api/run-specs/",
    "/api/runs/",
    "/api/client/releases/",
    "/api/testers/modules",
)

_PUBLIC_GRAPH_READ_RE = re.compile(
    r"/api/research-graphs/[^/]+/(?:versions|active)$"
)

_SERVICE_WRITE_PATTERNS = {
    "POST": (
        r"/api/agent-flow/agents/[A-Za-z0-9._-]{1,256}/resume",
        r"/api/product-groups",
        r"/api/runs/capability-preview",
        r"/api/runs(?:/preview)?",
        r"/api/runs/[^/]{1,128}/clone-workspace",
        r"/api/jobs/[A-Za-z0-9._-]{1,128}/(?:approve|cancel|continue|retry)",
    ),
    "PUT": (),
    "DELETE": (),
    "PATCH": (
        r"/api/profile-research/[^/]{1,512}/lifecycle",
    ),
}

_JOB_ANALYSIS_PATHS = {
    "/group-detail": "/get_group_detail",
    "/group-ranking-detail": "/get_group_ranking_detail",
    "/group-snapshot": "/get_group_snapshot",
    "/group-order-flow": "/get_group_order_flow",
}


def _catalog_source_ids(query: dict[str, list[str]]) -> tuple[str, ...]:
    """Resolve repeated/comma-separated source filters for Manager catalogs."""
    from server.services.product_catalog_projection import (
        catalog_source_ids,
        normalize_source_ids,
    )

    requested = [
        item.strip()
        for value in query.get("data_source", [])
        for item in str(value).split(",")
        if item.strip()
    ]
    return (
        normalize_source_ids(requested)
        if requested else catalog_source_ids()
    )


class ManagerState(
    SessionStateMixin,
    RoutingStateMixin,
    JobProjectionStateMixin,
    WorktreeStateMixin,
    ProcessStateMixin,
):
    def __init__(
        self,
        repo: Path,
        python: str,
        data_root: Path | None = None,
        *,
        server_role: str | None = None,
        server_id: str | None = None,
        fixed_port: int | None = None,
        fixed_branch: str | None = None,
        features: tuple[str, ...] = (),
        state_root: Path | None = None,
        fixed_daemon_socket: str | Path | None = None,
    ) -> None:
        self.repo = repo.resolve()
        self.runtime_source_root = _REPO_ROOT.resolve()
        self.vibe_trading_root = VIBE_TRADING_ROOT
        self.python = python
        self.server_role = str(
            server_role or os.environ.get("FACTORTESTER_SERVER_ROLE") or "feat"
        ).strip().lower()
        if self.server_role not in {"main", "feat"}:
            raise ValueError("server_role must be main or feat")
        self.server_id = str(
            server_id or os.environ.get("FACTORTESTER_SERVER_ID") or "local"
        ).strip()
        if not self.server_id:
            raise ValueError("server_id is required")
        raw_fixed_port = fixed_port
        if raw_fixed_port is None:
            raw_fixed_port = os.environ.get("FACTORTESTER_FIXED_PORT", "0")
        try:
            self.fixed_port = int(raw_fixed_port or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("fixed_port must be an integer") from exc
        if self.fixed_port and not 1 <= self.fixed_port <= 65535:
            raise ValueError("fixed_port must be between 1 and 65535")
        self.fixed_branch = str(
            fixed_branch
            or os.environ.get("FACTORTESTER_FIXED_BRANCH")
            or ("main" if self.server_role == "main" else "")
        ).strip()
        self.fixed_daemon_socket = (
            str(
                fixed_daemon_socket
                or os.environ.get("FACTORTESTER_FIXED_DAEMON_SOCKET")
                or ""
            ).strip()
            or None
        )
        self.server_features = tuple(sorted({
            str(item).strip()
            for item in features
            if str(item).strip()
        }))
        # These are instance-level deployment controls.  A local development
        # Manager remains convenient by default, while a public Manager can
        # opt into a hard login boundary from its service environment without
        # changing the application code or another server's behavior.
        self.require_login_for_ui = _env_bool(
            "FACTORTESTER_REQUIRE_LOGIN_FOR_UI", False,
        )
        self.public_registration_enabled = _env_bool(
            "FACTORTESTER_ALLOW_PUBLIC_REGISTRATION",
            not self.require_login_for_ui,
        )
        self.require_device_auth = _env_bool(
            "FACTORTESTER_REQUIRE_DEVICE_AUTH", False,
        )
        self.public_server = _env_bool(
            "FACTORTESTER_PUBLIC_SERVER", self.require_device_auth,
        )
        self.federation_registration_token = os.environ.get(
            "FACTORTESTER_FEDERATION_REGISTRATION_TOKEN", ""
        ).strip()
        # Manager control state belongs to the source checkout, while
        # user-visible research publications are data and must survive a
        # checkout/release change.  Keep an explicit override for tests and
        # alternate installations; the normal layout is GTHT/FactorTester
        # next to the Codes repository.
        self.data_root = (
            data_root.expanduser().resolve()
            if data_root is not None
            else self.repo.parent / "FactorTester"
        )
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.processes: dict[str, ServiceBundle] = {}
        self.vibe_process: subprocess.Popen | None = None
        self.state_root = (
            state_root.expanduser().resolve()
            if state_root is not None
            else self.repo / ".workspace" / "flask-manager"
        )
        self.log_dir = self.state_root / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.capability_path = self.state_root / "manager-capability.key"
        self.federation_proxy_path = self.state_root / "federation-proxy.key"
        self.artifact_ticket_path = self.state_root / "artifact-data-ticket.key"
        self.release_root = self.state_root / "client-releases"
        self.sessions_path = self.state_root / "sessions.json"
        # Account, organisation, hierarchy, profile, quota, and device
        # identity records share one PostgreSQL control plane when deployed.
        # The constructor is lazy: an unavailable database is reported by the
        # relevant request instead of preventing a local Manager from starting.
        self.control_store = control_store_from_env()
        self.device_registry = DeviceRegistry(
            self.state_root / "device-registry.json",
            server_id=self.server_id,
            control_store=self.control_store,
            public_server=self.public_server,
        )
        self.device_authorizations = DeviceAuthorizationStore(
            self.state_root / "device-authorizations.json",
            server_id=self.server_id,
            control_store=self.control_store,
        )
        self.device_challenges = DeviceChallengeStore()
        self.job_index = ManagerJobIndex(
            self.state_root / "job-index.sqlite",
            server_id=self.server_id,
        )
        self._local_job_route_cache: dict[int, ServiceRoute] = {}
        self.federation_registry = FederatedServerRegistry(
            self.state_root / "federation-registry.json",
        )
        self.federation_config_store = FederationConfigStore(
            self.state_root / "federation-config.json",
        )
        self.federation_gateway = FederatedGateway()
        self.federation_announcer: FederationAnnouncer | None = None
        self.federation_sync = FederationSyncWorker(
            server_id=self.server_id,
            job_index=self.job_index,
            gateway=self.federation_gateway,
            peer_provider=lambda: self.federation_registry.servers(
                include_offline=True,
            ),
            local_refresh=self.refresh_local_job_projection,
        )
        self.artifact_data_process: subprocess.Popen | None = None
        self.federation_peer_latency_ms: float | None = None
        self._capability_cache: dict[
            tuple[str, int, str], tuple[float, dict[str, object]]
        ] = {}
        self._capability_cache_lock = threading.RLock()
        self._sessions = self._load_sessions()
        self._session_lock = threading.Lock()
        self.public_research = PublicResearchLibrary(
            self.data_root / "public-research",
        )
        self.client_state = ClientStateService()
        self.test_authoring = TestAuthoringService()
        # The Manager exposes several application projections from one Python
        # process.  Their first call imports overlapping FactorTester packages;
        # concurrent first-page requests can otherwise observe partially
        # initialized modules or trigger Python's cross-module deadlock guard.
        # Keep the application boundary serialized.  Worker execution remains
        # independent and is still delegated to the selected service port.
        self.application_request_lock = threading.RLock()
        self.user_preferences = UserPreferenceStore(
            self.state_root / "user-preferences",
        )
        self.gateway = ServiceGateway(
            available_ports=self.service_ports,
            capability_token=self.capability_token,
        )
        self.sqlite_web = ManagerSQLiteWeb(self)

    @staticmethod
    def _authenticate_credentials(
        username: str,
        password: str,
        *,
        control_store: object | None = None,
    ) -> tuple[str, str]:
        """Invoke the composition-root authentication seam."""
        if control_store is None:
            return _authenticate_user(username, password)
        return _authenticate_user(
            username,
            password,
            control_store=control_store,
        )

    @staticmethod
    def _role_for_account(account: dict[str, object]) -> str:
        return _account_role(account)

    @staticmethod
    def _port_is_in_use(port: int) -> bool:
        """Keep the historical runtime monkeypatch seam at the root."""
        return port_in_use(port)







def page(state: ManagerState, message: str = "") -> bytes:
    lan = _lan_ip()
    rows = []
    for wt in state.worktrees():
        instance_id = state.instance_id(wt)
        if wt.port == 0:
            # No issue number — show warning, no Start/Stop actions
            rows.append(
                f"""
            <tr class="orphan">
              <td><strong>{html.escape(wt.label)}</strong><div class="muted">{html.escape(wt.branch)} · {html.escape(wt.head)}</div></td>
              <td><code>{html.escape(instance_id)}</code></td>
              <td><span class="muted">—</span></td>
              <td><span class="pill orphan-pill">no-issue</span></td>
              <td><span class="muted">⚠️ 建议清理：分支名不含 issue 编号</span></td>
            </tr>
            """
            )
            continue
        running = state.is_running(wt.path)
        occupied = port_in_use(wt.port) and not running
        daemon_running = state.daemon_running(wt.path)
        status = "running" if running and daemon_running else ("degraded" if running else ("occupied" if occupied else "stopped"))
        start_disabled = "disabled" if running or occupied else ""
        stop_disabled = "" if running or daemon_running else "disabled"
        open_disabled = "" if running or occupied else "disabled"
        rows.append(
            f"""
            <tr>
              <td><strong>{html.escape(wt.label)}</strong><div class="muted">{html.escape(wt.branch)} · {html.escape(wt.head)}</div></td>
              <td><code>{html.escape(instance_id)}</code></td>
              <td><a href="http://localhost:{wt.port}/" target="_blank" title="localhost">{wt.port}</a> <span class="muted">|</span> <a href="http://{lan}:{wt.port}/" target="_blank" title="LAN ({lan})" class="lan-link">🌐</a></td>
              <td><span class="pill {status}">{status}</span></td>
              <td>
                <form method="post" action="/start"><input type="hidden" name="instance_id" value="{html.escape(instance_id)}"><button {start_disabled}>Start</button></form>
                <form method="post" action="/stop"><input type="hidden" name="instance_id" value="{html.escape(instance_id)}"><button {stop_disabled}>Stop</button></form>
                <form method="post" action="/restart-api"><input type="hidden" name="instance_id" value="{html.escape(instance_id)}"><button {'' if daemon_running else 'disabled'}>Restart API</button></form>
                <form method="post" action="/restart-bundle"><input type="hidden" name="instance_id" value="{html.escape(instance_id)}"><button {'' if daemon_running else 'disabled'}>Restart Bundle</button></form>
                <form method="post" action="/force-stop"><input type="hidden" name="instance_id" value="{html.escape(instance_id)}"><button {stop_disabled}>Force Stop</button></form>
                <a class="button {open_disabled}" href="http://localhost:{wt.port}/" target="_blank">Open</a>
                <a class="button {open_disabled}" href="http://{lan}:{wt.port}/" target="_blank" title="LAN 访问">🌐 Open</a>
              </td>
            </tr>
            """
        )
    msg = f"<div class='message'>{html.escape(message)}</div>" if message else ""
    vibe_running = state.vibe_running()
    vibe_occupied = port_in_use(VIBE_TRADING_PORT) and not vibe_running
    vibe_status = (
        "running" if vibe_running else "occupied" if vibe_occupied else "stopped"
    )
    vibe_start_disabled = "disabled" if vibe_running or vibe_occupied else ""
    vibe_stop_disabled = "" if vibe_running else "disabled"
    vibe_open_disabled = "" if vibe_running or vibe_occupied else "disabled"
    vibe_row = f"""
      <tr>
        <td><strong>Vibe-Trading</strong><div class="muted">research UI + MaxA MCP gateway</div></td>
        <td><code>service-vibe-trading</code></td>
        <td><a href="http://localhost:{VIBE_TRADING_PORT}/" target="_blank">{VIBE_TRADING_PORT}</a></td>
        <td><span class="pill {vibe_status}">{vibe_status}</span></td>
        <td>
          <form method="post" action="/vibe/start"><input type="hidden" name="instance_id" value="service-vibe-trading"><button {vibe_start_disabled}>Start</button></form>
          <form method="post" action="/vibe/stop"><input type="hidden" name="instance_id" value="service-vibe-trading"><button {vibe_stop_disabled}>Stop</button></form>
          <a class="button {vibe_open_disabled}" href="http://localhost:{VIBE_TRADING_PORT}/" target="_blank">Open</a>
        </td>
      </tr>
    """
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>FactorTester Worktree Flask Manager</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #1f2937; }}
    h1 {{ font-size: 22px; margin: 0 0 16px; }}
    table {{ border-collapse: collapse; width: 100%; table-layout: fixed; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 10px; text-align: left; vertical-align: top; }}
    th:nth-child(1), td:nth-child(1) {{ width: auto; }}
    th:nth-child(2), td:nth-child(2) {{ width: auto; }}
    th:nth-child(3), td:nth-child(3) {{ width: 85px; }}
    th:nth-child(4), td:nth-child(4) {{ width: 85px; }}
    th:nth-child(5), td:nth-child(5) {{ width: 280px; white-space: nowrap; }}
    th {{ background: #f9fafb; font-size: 12px; text-transform: uppercase; color: #6b7280; }}
    code {{ font-size: 12px; color: #374151; word-break: break-all; }}
    form {{ display: inline; }}
    button, .button {{ border: 1px solid #cbd5e1; background: #fff; color: #111827; padding: 4px 9px; border-radius: 6px; text-decoration: none; font-size: 13px; cursor: pointer; margin-right: 4px; }}
    button:disabled, .disabled {{ opacity: .45; pointer-events: none; cursor: default; }}
    .muted {{ color: #6b7280; font-size: 12px; margin-top: 2px; }}
    .pill {{ display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 12px; font-weight: 600; }}
    .running {{ background: #dcfce7; color: #166534; }}
    .stopped {{ background: #f3f4f6; color: #374151; }}
    .occupied {{ background: #fef3c7; color: #92400e; }}
    .degraded {{ background: #fee2e2; color: #991b1b; }}
    .orphan {{ background: #fef2f2; }}
    .orphan-pill {{ background: #fee2e2; color: #991b1b; }}
    .message {{ padding: 8px 10px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px; margin-bottom: 12px; }}
    .lan-link {{ text-decoration: none; font-size: 14px; }}
  </style>
</head>
<body>
  <h1>FactorTester Worktree Flask Manager</h1>
  <p class="muted" style="margin-bottom:4px">Use Start/Stop for ordinary parallel servers. For VS Code breakpoints, launch the matching <code>Flask Debug: ...</code> configuration on the same worktree/port while that port is stopped here.</p>
  <p class="muted" style="margin-bottom:12px">🌐 局域网访问本机: <strong>{lan}</strong>（同一热点/网络下的设备使用此 IP + 端口号访问）</p>
  {msg}
  <table>
    <thead><tr><th>Worktree</th><th>Instance</th><th>Port</th><th>Status</th><th>Actions</th></tr></thead>
    <tbody>{vibe_row}{''.join(rows)}</tbody>
  </table>
</body>
</html>""".encode("utf-8")


class Handler(DeviceNetworkRoutesMixin, BaseHTTPRequestHandler):
    state: ManagerState

    def _client_ip(self) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
        peer = ipaddress.ip_address(self.client_address[0])
        if not peer.is_loopback:
            return peer
        forwarded = self.headers.get(
            "X-Forwarded-For", ""
        ).split(",", 1)[0].strip()
        if not forwarded:
            return peer
        try:
            return ipaddress.ip_address(forwarded)
        except ValueError:
            return peer

    def _is_loopback_client(self) -> bool:
        return self._client_ip().is_loopback

    def _is_private_lan_client(self) -> bool:
        client = self._client_ip()
        return client.is_private or client.is_link_local

    def _is_https_proxy_request(self) -> bool:
        try:
            peer = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        forwarded_proto = self.headers.get(
            "X-Forwarded-Proto", ""
        ).split(",", 1)[0].strip().lower()
        return peer.is_loopback and forwarded_proto == "https"

    def _is_direct_https_request(self) -> bool:
        """Whether this Manager socket itself is serving authenticated TLS."""
        return bool(getattr(self.server, "tls_enabled", False))

    def _is_secure_transport(self) -> bool:
        return self._is_direct_https_request() or self._is_https_proxy_request()

    def _has_secure_ui_transport(self) -> bool:
        return (
            self._is_direct_https_request()
            or
            self._is_loopback_client()
            or self._is_private_lan_client()
            or self._is_https_proxy_request()
        )

    def _is_same_origin_browser_action(self) -> bool:
        if not self._is_loopback_client():
            return False
        origin = self.headers.get("Origin", "").rstrip("/")
        host = self.headers.get("Host", "").strip()
        return bool(origin and host and origin == f"http://{host}")

    def _has_capability(self) -> bool:
        supplied = self._bearer_token()
        return (
            bool(supplied)
            and hmac.compare_digest(supplied, self.state.capability_token())
        )

    def _bearer_token(self) -> str:
        scheme, _, supplied = self.headers.get("Authorization", "").partition(" ")
        if scheme.lower() == "bearer" and supplied:
            return supplied.strip()
        # Embedded documentation/database pages are ordinary browser
        # navigations and cannot attach the SPA Authorization header.  The
        # Manager login cookie is HttpOnly and is therefore only parsed here.
        for item in self.headers.get("Cookie", "").split(";"):
            name, separator, value = item.strip().partition("=")
            if separator and name == "ft-manager-session":
                return value.strip()
        return ""

    def _session(self) -> dict[str, object] | None:
        return self.state.session(self._bearer_token())

    def _serve_login_page(self, parsed) -> None:
        requested = parse_qs(parsed.query, keep_blank_values=True).get(
            "next", ["/"]
        )[0]
        if self.state.require_device_auth and not self._is_loopback_client():
            self._serve_compliance_page(str(requested or "/"))
            return
        body = manager_login_page(
            str(requested or "/"),
            accept_language=self.headers.get("Accept-Language", ""),
        )
        self._send_html(body)

    def _send_html(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; form-action 'self'; base-uri 'none'; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'",
        )
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_compliance_page(self, next_path: str = "/") -> None:
        body = manager_compliance_page(
            next_path,
            accept_language=self.headers.get("Accept-Language", ""),
        )
        self._send_html(body)

    def _serve_device_gate(self, next_path: str = "/") -> None:
        # Keep the old endpoint as a compatibility alias. New public requests
        # go directly to the compliance page, which silently attempts device
        # authentication without exposing an intermediate UI.
        self._serve_compliance_page(next_path)

    def _public_login_gate(self, parsed, *, method: str) -> bool:
        """Apply the instance-level public UI policy before route dispatch."""
        if not self.state.require_login_for_ui:
            # The local Manager deliberately keeps its existing unauthenticated
            # panel behavior.  Route-specific APIs still enforce their own
            # user or capability checks below.
            return True

        path = parsed.path
        if path in {"/compliance", "/device-gate"}:
            return True

        if path == "/device-authorize":
            if not self.state.public_server:
                json_response(self, {
                    "success": False,
                    "error": "device authorization is available only on a public Manager",
                }, 404)
                return False
            if not self._has_secure_ui_transport():
                json_response(self, {
                    "success": False,
                    "error": "device authorization requires HTTPS",
                }, 400)
                return False
            return True

        if path == "/api/device/authorization/redeem":
            if not self.state.public_server:
                json_response(self, {
                    "success": False,
                    "error": "device authorization is available only on a public Manager",
                }, 404)
                return False
            if not self._has_secure_ui_transport():
                json_response(self, {
                    "success": False,
                    "error": "device authorization requires HTTPS",
                }, 400)
                return False
            return True

        if method == "GET" and path == "/api/device/summary":
            # The compliance page may show an aggregate count before the
            # browser has a session.  It contains no usernames or device IDs.
            return True

        if method == "GET" and path == "/api/server/network-info":
            # The local home page may display the Manager-provided LAN
            # address before login.  A public endpoint still needs a session;
            # the route itself repeats this distinction as defence in depth.
            if self._is_private_lan_client():
                return True

        if path in {"/api/device/challenge", "/api/device/verify"}:
            if not self._has_secure_ui_transport():
                json_response(
                    self,
                    {
                        "success": False,
                        "error": "HTTPS is required for device authentication",
                    },
                    400,
                )
                return False
            return True

        if path == "/login":
            return True

        # Signed client release files are distribution artifacts, not an
        # interactive user interface.  They must remain downloadable before a
        # client has a session so an existing FTClient can update itself.
        if method == "GET" and path.startswith("/api/client/releases/"):
            return True

        machine_request = (
            path.startswith("/api/federation/")
            or path == "/api/worktrees"
            or path in _MANAGER_ACTION_PATHS
        )
        if machine_request:
            if not self._has_secure_ui_transport():
                json_response(
                    self,
                    {
                        "success": False,
                        "error": "HTTPS is required for public Manager communication",
                    },
                    400,
                )
                return False
            # Federation handlers validate their endpoint-specific machine
            # token.  We only keep them outside the browser login redirect so
            # an authenticated peer can continue to operate normally.
            if path.startswith("/api/federation/"):
                return True
            if self._has_capability():
                return True

        session = self._session()
        if session is not None and self._has_secure_ui_transport():
            return True

        if path.startswith("/api/") or method != "GET":
            status = 400 if not self._has_secure_ui_transport() else 401
            headers = (
                {}
                if status == 400
                else {"WWW-Authenticate": "Bearer"}
            )
            json_response(
                self,
                {
                    "success": False,
                    "error": (
                        "HTTPS is required for public Manager access"
                        if status == 400
                        else (
                            "device authentication required"
                            if self.state.require_device_auth
                            else "login required"
                        )
                    ),
                },
                status,
                headers=headers,
            )
            return False

        requested = path + (f"?{parsed.query}" if parsed.query else "")
        destination = "/compliance?next=" if self.state.require_device_auth else "/login?next="
        location = destination + quote(
            manager_safe_login_next(requested), safe="/?=&%"
        )
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _authorization_bearer(self) -> str:
        scheme, _, supplied = self.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer":
            return ""
        return supplied.strip()

    def _has_federation_registration_token(self) -> bool:
        expected = self.state.federation_registration_token
        supplied = self._authorization_bearer()
        return bool(expected and supplied and hmac.compare_digest(supplied, expected))

    def _has_federation_proxy_token(self) -> bool:
        supplied = self._authorization_bearer()
        return bool(
            supplied
            and hmac.compare_digest(supplied, self.state.federation_proxy_token())
        )

    @staticmethod
    def _federation_path_allowed(path: str) -> bool:
        return (
            path == "/api/jobs"
            or path.startswith("/api/jobs/")
            or path == "/api/runs"
            or path.startswith("/api/runs/")
            or path.startswith("/api/agent-flow/")
            or path.startswith("/api/research-graphs/")
            or path.startswith("/api/research-evidence/")
            or path.startswith("/api/trial-plans/")
            or path.startswith("/api/run-specs/")
            or path.startswith("/api/profile-research/")
            or path.startswith("/api/product-groups")
        )

    def _federation_register(self) -> None:
        if not self._has_federation_registration_token():
            json_response(
                self,
                {"success": False, "error": "federation registration is unauthorized"},
                401,
            )
            return
        try:
            value = self.state.federation_registry.register(
                self._json_body(512 * 1024),
            )
        except (TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        public = {
            key: item
            for key, item in value.items()
            if key not in {"proxy_token"}
        }
        forwarded_proto = str(
            self.headers.get("X-Forwarded-Proto") or "http"
        ).split(",", 1)[0].strip().lower()
        if forwarded_proto not in {"http", "https"}:
            forwarded_proto = "http"
        advertised_endpoint = os.environ.get(
            "FACTORTESTER_MANAGER_PUBLIC_ENDPOINT", ""
        ).strip().rstrip("/")
        if not advertised_endpoint:
            host = str(self.headers.get("Host") or "").strip()
            if host:
                advertised_endpoint = f"{forwarded_proto}://{host}"
        peer = None
        if advertised_endpoint:
            try:
                peer = self.state.peer_registration_payload(advertised_endpoint)
            except (OSError, RuntimeError, ValueError) as exc:
                sys.stderr.write(f"[federation] peer descriptor unavailable: {exc}\n")
        # Registration is service discovery only; task summaries are on-demand.
        json_response(self, {
            "success": True,
            "server": public,
            # This is returned only over the already authenticated
            # registration channel.  It lets the caller route back to this
            # Manager's fixed service (normally remote 8000) without exposing
            # any service port directly.
            "peer": peer,
        })

    def _federation_sync_events(self) -> None:
        """Serve the local Manager event stream to an authenticated peer."""
        if not self._has_federation_proxy_token():
            json_response(
                self,
                {"success": False, "error": "federation proxy is unauthorized"},
                401,
            )
            return
        try:
            payload = self._json_body(2 * 1024 * 1024)
            requester = str(payload.get("requester_server_id") or "").strip()
            after_sequence = int(payload.get("after_sequence") or 0)
            limit = int(payload.get("limit") or 100)
            if not requester:
                raise ValueError("requester_server_id is required")
            if requester == self.state.server_id:
                raise ValueError("requester_server_id must identify a peer")
            if after_sequence < 0:
                raise ValueError("after_sequence must not be negative")
            if not 1 <= limit <= 200:
                raise ValueError("limit must be between 1 and 200")
            value = self.state.job_index.events_for_peer(
                requester,
                after_sequence=after_sequence,
                limit=limit,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, value)

    def _federation_jobs_query(self) -> None:
        """Serve a bounded local task projection to a peer Manager.

        The proxy token authenticates the peer-to-peer request.  The local
        aggregation methods are explicitly called with federation disabled so
        this endpoint cannot recurse through the other Manager.
        """
        if not self._has_federation_proxy_token():
            json_response(
                self,
                {"success": False, "error": "federation proxy is unauthorized"},
                401,
            )
            return
        try:
            payload = self._json_body(64 * 1024)
            requester = str(payload.get("requester_server_id") or "").strip()
            principal = str(payload.get("principal") or "").strip()
            scope = str(payload.get("scope") or "").strip().lower()
            page = int(payload.get("page") or 1)
            limit = int(payload.get("limit") or 100)
            if not requester:
                raise ValueError("requester_server_id is required")
            if requester == self.state.server_id:
                raise ValueError("requester_server_id must identify a peer")
            if not principal:
                raise ValueError("principal is required")
            if scope not in {"mine", "server"}:
                raise ValueError("scope must be mine or server")
            if page < 1 or not 1 <= limit <= 100:
                raise ValueError("page or limit is invalid")
            if scope == "server":
                value = self.state.aggregate_server_jobs(
                    principal=principal,
                    cursor="",
                    limit=limit,
                    _allow_federation=False,
                )
            else:
                value = self.state.aggregate_account_jobs(
                    principal=principal,
                    scope="mine",
                    page=page,
                    limit=limit,
                    _allow_federation=False,
                )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {
            **value,
            "success": True,
            "source_server_id": self.state.server_id,
            "source_scope": scope,
        })

    def _federation_sync_reconcile(self) -> None:
        """Return a bounded current projection for a peer's repair request."""
        if not self._has_federation_proxy_token():
            json_response(
                self,
                {"success": False, "error": "federation proxy is unauthorized"},
                401,
            )
            return
        try:
            payload = self._json_body(2 * 1024 * 1024)
            requester = str(payload.get("requester_server_id") or "").strip()
            raw_job_ids = payload.get("job_ids") or []
            limit = int(payload.get("limit") or 200)
            if not requester:
                raise ValueError("requester_server_id is required")
            if requester == self.state.server_id:
                raise ValueError("requester_server_id must identify a peer")
            if not isinstance(raw_job_ids, list):
                raise ValueError("job_ids must be a list")
            if not 1 <= limit <= 200:
                raise ValueError("limit must be between 1 and 200")
            jobs = self.state.job_index.reconcile_for_peer(
                requester,
                job_ids=raw_job_ids[:200],
                limit=limit,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {
            "success": True,
            "source_server_id": self.state.server_id,
            "jobs": jobs,
        })

    def _federation_sync(self) -> None:
        """Run one manual event pull from the Manager settings page."""
        if not self._require_super_admin_session():
            return
        json_response(self, {
            "success": True,
            "reports": self.state.sync_federation_once(),
        })

    def _federation_artifact_ticket(self) -> None:
        """Mint a ticket for this Manager's host-local 7997 data plane."""
        if not self._has_federation_proxy_token():
            json_response(
                self,
                {"success": False, "error": "federation proxy is unauthorized"},
                401,
            )
            return
        try:
            payload = self._json_body(64 * 1024)
            server_id = str(payload.get("server_id") or "").strip()
            job_id = str(payload.get("job_id") or "").strip()
            name = str(payload.get("name") or "").strip()
            principal = str(payload.get("principal") or "").strip()
            preview = bool(payload.get("preview"))
            archive = bool(payload.get("archive"))
            if server_id != self.state.server_id:
                raise ValueError("federation target server_id does not match")
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", job_id):
                raise ValueError("job_id is invalid")
            if archive:
                name = "__archive__"
            elif not name or "/" in name or "\\" in name or ".." in name:
                raise ValueError("artifact name is invalid")
            if not principal:
                raise ValueError("federation principal is required")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        from server.jobs.repository import JobRepository

        repository = JobRepository()
        job = repository.load(job_id)
        if job is None:
            json_response(self, {"success": False, "error": "job was not found"}, 404)
            return
        if principal != "__public_jobs__" and job.owner != principal:
            json_response(self, {"success": False, "error": "job was not found"}, 404)
            return
        if not archive:
            metadata = repository.load_artifact(
                job_id=job_id,
                name=name,
                owner=job.owner,
            )
            if metadata is None or str(metadata.get("state") or "") != "active":
                json_response(self, {"success": False, "error": "artifact was not found"}, 404)
                return
            if (
                principal == "__public_jobs__"
                and str(metadata.get("artifact_role") or "output") == "input"
            ):
                json_response(self, {"success": False, "error": "登录后才能查看运行输入"}, 401)
                return
        endpoint = str(
            os.environ.get("FACTORTESTER_MANAGER_PUBLIC_ENDPOINT") or ""
        ).strip().rstrip("/")
        if not endpoint:
            host = str(self.headers.get("Host") or "").strip()
            if host:
                endpoint = f"http://{host}"
        try:
            data_endpoint = artifact_data_endpoint(
                endpoint=endpoint or "http://127.0.0.1:7998",
                port=artifact_data_port(),
            )
            ticket = self.state.artifact_ticket_codec().issue(
                owner=job.owner,
                job_id=job_id,
                name=name,
                server_id=self.state.server_id,
                preview=preview,
            )
        except (OSError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return
        json_response(self, {
            "success": True,
            "ticket": ticket,
            "data_endpoint": data_endpoint,
            "url": artifact_data_url(
                data_endpoint,
                job_id=job_id,
                name=name,
                ticket=ticket,
            ),
        })

    def _federation_proxy(self) -> None:
        if not self._has_federation_proxy_token():
            json_response(
                self,
                {"success": False, "error": "federation proxy is unauthorized"},
                401,
            )
            return
        try:
            payload = self._json_body(16 * 1024 * 1024)
            server_id = str(payload.get("server_id") or "").strip()
            port = int(payload.get("port") or 0)
            path = str(payload.get("path") or "").strip()
            principal = str(payload.get("principal") or "").strip()
            method = str(payload.get("method") or "GET").upper()
            content_type = str(payload.get("content_type") or "application/json")
            origin_server_id = str(payload.get("origin_server_id") or "").strip()
            if server_id != self.state.server_id:
                raise ValueError("federation target server_id does not match")
            if not 1 <= port <= 65535:
                raise ValueError("federation target port is invalid")
            if not principal:
                raise ValueError("federation principal is required")
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                raise ValueError("federation method is not supported")
            if not self._federation_path_allowed(path):
                raise ValueError("federation path is not allowed")
            encoded = str(payload.get("body_b64") or "")
            body = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        try:
            route = self.state.route_for(
                server_id=self.state.server_id,
                port=port,
            )
            response = self.state.route_request(
                route,
                path=path,
                principal=principal,
                method=method,
                body=body or None,
                content_type=content_type,
            )
        except TargetUnavailable as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return
        except (TargetNotFound, ConnectionError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 502)
            return
        if method == "POST" and path == "/api/runs" and origin_server_id:
            self.state.record_run_submission(
                response,
                principal=principal,
                route=route,
                origin_server_id=origin_server_id,
            )
        envelope = {
            "success": True,
            "status": response.status,
            "content_type": response.content_type,
            "content_disposition": response.content_disposition,
            "etag": response.etag,
            "body_b64": base64.b64encode(response.body).decode("ascii"),
        }
        json_response(self, envelope, response.status)

    def _federation_stream(self) -> None:
        """Proxy one job SSE stream to a service owned by this Manager.

        The peer Manager is the only cross-host hop.  This endpoint never
        resolves another remote route, which prevents a registration cycle
        from turning into an unbounded proxy chain.
        """
        if not self._has_federation_proxy_token():
            json_response(
                self,
                {"success": False, "error": "federation proxy is unauthorized"},
                401,
            )
            return
        try:
            payload = self._json_body(256 * 1024)
            server_id = str(payload.get("server_id") or "").strip()
            port = int(payload.get("port") or 0)
            path = str(payload.get("path") or "").strip()
            principal = str(payload.get("principal") or "").strip()
            last_event_id = str(payload.get("last_event_id") or "").strip()[:512]
            parsed_path = urlparse(path)
            if server_id != self.state.server_id:
                raise ValueError("federation target server_id does not match")
            if not 1 <= port <= 65535:
                raise ValueError("federation target port is invalid")
            if not principal:
                raise ValueError("federation principal is required")
            if parsed_path.scheme or parsed_path.netloc:
                raise ValueError("federation stream path must be relative")
            if not re.fullmatch(
                r"/api/jobs/[A-Za-z0-9._-]{1,128}/stream",
                parsed_path.path,
            ):
                raise ValueError("federation stream path is not allowed")
            if not self._federation_path_allowed(parsed_path.path):
                raise ValueError("federation path is not allowed")
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return

        try:
            route = self.state.route_for(
                server_id=self.state.server_id,
                port=port,
            )
            if route.remote:
                raise ValueError("federation stream cannot be chained")
        except TargetUnavailable as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return
        except (TargetNotFound, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 502)
            return

        forwarded_path = parsed_path.path
        if parsed_path.query:
            forwarded_path += f"?{parsed_path.query}"
        request = Request(
            f"http://127.0.0.1:{route.port}{forwarded_path}",
            headers={
                "Accept": "text/event-stream",
                "X-FactorTester-Principal": principal,
                "X-FactorTester-Manager": self.state.capability_token(),
                "Last-Event-ID": last_event_id,
            },
        )
        try:
            upstream = urlopen(request, timeout=15)
        except HTTPError as exc:
            body = exc.read(4 * 1024 * 1024)
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get_content_type())
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        except (URLError, OSError) as exc:
            json_response(
                self,
                {"success": False, "error": "local service stream is unavailable"},
                503,
            )
            return

        with upstream:
            self.send_response(getattr(upstream, "status", 200))
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("X-FactorTester-Service-Port", str(route.port))
            self.send_header("X-FactorTester-Service-Server", route.server_id)
            if route.branch:
                self.send_header("X-FactorTester-Service-Branch", route.branch)
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                while chunk := upstream.read(4096):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass

    def _federation_capabilities(self) -> None:
        """Return this Manager's data-source capability projection to a peer."""
        if not self._has_federation_proxy_token():
            json_response(
                self,
                {"success": False, "error": "federation capability is unauthorized"},
                401,
            )
            return
        try:
            payload = self._json_body(4 * 1024 * 1024)
            if not isinstance(payload, dict):
                raise ValueError("federation capability payload must be an object")
            value = self.state.local_capability_snapshot(payload)
            requested_port = payload.get("port")
            requested_branch = str(payload.get("branch") or "").strip()
            targets = self.state.local_service_routes(include_offline=True)
            if requested_port not in (None, ""):
                try:
                    requested_port = int(requested_port)
                except (TypeError, ValueError) as exc:
                    raise ValueError("capability port must be an integer") from exc
                targets = [
                    route for route in targets
                    if route.port == requested_port
                    and (not requested_branch or route.branch == requested_branch)
                ]
                if not targets:
                    raise ValueError("requested capability port is not owned by this Manager")
            target = min(
                targets,
                key=self.state.route_selection_key,
                default=None,
            )
        except (TypeError, ValueError, OSError, RuntimeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {
            "success": True,
            "server_id": self.state.server_id,
            "server_role": self.state.server_role,
            "target": (
                {
                    "server_id": self.state.server_id,
                    "server_role": self.state.server_role,
                    **target.as_dict(),
                }
                if target is not None else {
                    "server_id": self.state.server_id,
                    "server_role": self.state.server_role,
                }
            ),
            "ports": [
                route.as_dict()
                for route in self.state.local_service_routes(
                    include_offline=True,
                )
            ],
            **value,
        })

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
                for route in self.state.local_service_routes(include_offline=True)
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
            "control_database": self.state.control_database_status(),
            "available_ports": [
                route.as_dict()
                for route in self.state.local_service_routes(
                    include_offline=True,
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
        json_response(self, {"success": True, **value})

    def _serve_product_catalog(self, parsed) -> bool:
        """Serve the Manager-owned catalog without selecting a service port."""
        if not parsed.path.startswith("/api/catalog/"):
            return False
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return True
        principal = str(session["username"])
        query = parse_qs(parsed.query, keep_blank_values=True)
        category_id = str(query.get("category", [""])[0] or "").strip()
        try:
            if parsed.path == "/api/catalog/sources":
                value = {
                    "success": True,
                    "origin": "server",
                    "sources": self.state.federated_source_descriptors(
                        refresh=str(query.get("refresh", [""])[0]).lower()
                        in {"1", "true", "yes"},
                    ),
                }
            elif parsed.path == "/api/catalog/categories":
                value = {
                    "success": True,
                    "origin": "server",
                    "default_category_id": None,
                    "categories": self.state.client_state.product_categories(),
                }
            elif parsed.path == "/api/catalog/products":
                source_ids = _catalog_source_ids(query)
                value = {
                    "success": True,
                    "origin": "server",
                    "source_ids": list(source_ids),
                    "products": self.state.client_state.product_names(source_ids),
                }
            elif parsed.path == "/api/catalog/product-fields":
                product = self.state.client_state.product_fields(
                    query.get("name", [""])[0]
                )
                if product is None:
                    json_response(self, {
                        "success": False, "error": "产品不存在",
                    }, 404)
                    return True
                value = {
                    "success": True,
                    "origin": "server",
                    "name": product.get("name"),
                    "fields": product.get("fields", {}),
                }
            elif parsed.path == "/api/catalog/tree":
                source_ids = _catalog_source_ids(query)
                value = {
                    "success": True,
                    "origin": "server",
                    "category_id": category_id,
                    "source_ids": list(source_ids),
                    "tree": self.state.client_state.product_tree(
                        category_id, source_ids,
                    ),
                }
            elif parsed.path == "/api/catalog/contract-tree":
                source_ids = _catalog_source_ids(query)
                value = {
                    "success": True,
                    "origin": "server",
                    "category_id": category_id,
                    "source_ids": list(source_ids),
                    "nodes": self.state.client_state.contract_tree(
                        query.get("path", [""])[0], category_id, source_ids,
                    ),
                }
            elif parsed.path == "/api/catalog/contracts":
                value = self.state.client_state.product_contracts(
                    str(query.get("product", [""])[0] or ""),
                    start_date=query.get("start_date", [None])[0],
                    end_date=query.get("end_date", [None])[0],
                )
            elif parsed.path == "/api/catalog/product-groups":
                value = {
                    "success": True,
                    "origin": "server",
                    "groups": self.state.client_state.product_groups(principal),
                }
            else:
                match = re.fullmatch(
                    r"/api/catalog/product-groups/([^/]+)", parsed.path,
                )
                if match is None:
                    return False
                group = self.state.client_state.product_group(
                    principal, unquote(match.group(1)),
                )
                if group is None:
                    json_response(self, {
                        "success": False, "error": "产品组不存在",
                    }, 404)
                    return True
                value = {"success": True, "origin": "server", "group": group}
        except ValueError as exc:
            json_response(
                self,
                {"success": False, "error": str(exc)},
                int(getattr(exc, "status", 400)),
            )
            return True
        except (OSError, RuntimeError, ImportError, TypeError, KeyError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return True
        json_response(self, value)
        return True

    def _serve_factor_catalog(self, parsed) -> bool:
        """Serve read-only factor metadata without selecting a service port."""
        if not parsed.path.startswith("/api/catalog/factor"):
            return False
        session = self._session()
        if session is None:
            json_response(self, {
                "success": False, "error": "login required",
            }, 401)
            return True
        principal = str(session["username"])
        query = parse_qs(parsed.query, keep_blank_values=True)
        try:
            if parsed.path == "/api/catalog/factors":
                json_response(self, {
                    "success": True,
                    **self.state.client_state.factor_library(principal),
                })
                return True
            if parsed.path == "/api/catalog/factor-sets":
                items = self.state.client_state.factor_sets(
                    principal, str(query.get("query", [""])[0] or ""),
                )
                json_response(self, {
                    "success": True, "count": len(items), "items": items,
                })
                return True
            if parsed.path == "/api/catalog/factor-sets/detail":
                offset = max(0, int(query.get("offset", ["0"])[0] or 0))
                limit = min(100, max(
                    1, int(query.get("limit", ["100"])[0] or 100),
                ))
                value = self.state.client_state.factor_set_detail(
                    principal,
                    str(query.get("target_ref", [""])[0] or ""),
                    offset=offset,
                    limit=limit,
                )
                if value is None:
                    json_response(self, {
                        "success": False, "error": "Factor Set 不存在",
                    }, 404)
                else:
                    json_response(self, {
                        "success": True, "factor_set": value,
                    })
                return True
            if parsed.path == "/api/catalog/factor-sets/descriptor":
                value = self.state.client_state.factor_set_descriptor(
                    principal,
                    str(query.get("target_ref", [""])[0] or ""),
                )
                if value is None:
                    json_response(self, {
                        "success": False, "error": "Factor Set 不存在",
                    }, 404)
                else:
                    json_response(self, {
                        "success": True, "descriptor": value,
                    })
                return True
        except (
            OSError, RuntimeError, ImportError, TypeError, ValueError, KeyError,
        ) as exc:
            json_response(self, {
                "success": False, "error": str(exc),
            }, 503)
            return True
        return False

    def _serve_product_catalog_write(self, parsed) -> bool:
        """Serve Manager-owned catalog writes without a service port."""
        if parsed.path not in {
            "/api/catalog/prices",
            "/api/catalog/product-groups",
        }:
            return False
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return True
        try:
            payload = self._json_body(256 * 1024)
            if parsed.path == "/api/catalog/product-groups":
                name = str(payload.get("name") or "").strip()
                paths = payload.get("paths")
                if not name:
                    raise ValueError("产品组名称不能为空")
                if not isinstance(paths, list) or not paths:
                    raise ValueError("请选择至少一个品种路径")
                if not all(isinstance(path, str) and path.strip() for path in paths):
                    raise ValueError("产品路径必须是非空字符串")
                group = self.state.client_state.create_product_group(
                    str(session["username"]), name, paths,
                )
                if group is None:
                    json_response(self, {
                        "success": False, "error": "产品组名称已存在",
                    }, 409)
                    return True
                value = {"success": True, "origin": "server", "group": group}
            else:
                value = self.state.client_state.product_price_series(payload)
        except ValueError as exc:
            json_response(
                self,
                {"success": False, "error": str(exc)},
                int(getattr(exc, "status", 400)),
            )
            return True
        except (OSError, RuntimeError, ImportError, TypeError, KeyError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return True
        json_response(self, value)
        return True

    def _serve_test_authoring(self, parsed, *, method: str) -> bool:
        """Serve test editing state locally; never consult a worker port."""
        if not self.state.test_authoring.handles(parsed.path, method):
            return False
        session = self._session()
        if session is None:
            json_response(self, {
                "success": False, "error": "login required",
            }, 401)
            return True
        try:
            if method == "GET":
                response = self.state.test_authoring.get(
                    parsed.path, owner=str(session["username"]),
                )
            else:
                payload = {} if method == "DELETE" else self._json_body(1024 * 1024)
                response = self.state.test_authoring.write(
                    method, parsed.path, owner=str(session["username"]),
                    payload=payload,
                )
        except TestAuthoringError as exc:
            json_response(self, {
                "success": False, "error": str(exc), **exc.details,
            }, exc.status)
            return True
        except (KeyError, TypeError, ValueError) as exc:
            json_response(self, {
                "success": False, "error": str(exc),
            }, 400)
            return True
        except (OSError, RuntimeError, ImportError) as exc:
            sys.stderr.write(f"[manager] test authoring failed: {exc}\n")
            json_response(self, {
                "success": False, "error": "test authoring data is unavailable",
            }, 503)
            return True
        json_response(self, response.payload, response.status)
        return True

    def _serve_manager_application(self, parsed, *, method: str) -> bool:
        """Dispatch Manager-owned application state under one import boundary."""
        with self.state.application_request_lock:
            if method == "GET":
                return bool(
                    self._serve_test_authoring(parsed, method=method)
                    or self._serve_product_catalog(parsed)
                    or self._serve_factor_catalog(parsed)
                )
            return bool(
                self._serve_product_catalog_write(parsed)
                or self._serve_test_authoring(parsed, method=method)
            )

    def _has_manager_ui_session(self) -> bool:
        session = self.state.session(self._bearer_token())
        return bool(
            self._has_secure_ui_transport() and session
            and session["capabilities"]["manager"]
        )

    def _has_api_authorization(self) -> bool:
        return self._has_capability() or self._has_manager_ui_session()

    def _require_capability(self) -> bool:
        if self._has_capability():
            return True
        self.send_response(401)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("WWW-Authenticate", "Bearer")
        body = b'{"error":"manager capability required"}'
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def _job_ports(self, parsed, principal: str | None = None) -> list[int]:
        requested = parse_qs(parsed.query).get("port", [""])[0]
        indexed: list[int] = []
        if principal:
            match = re.fullmatch(
                r"/api/jobs/([A-Za-z0-9._-]{1,128})", parsed.path,
            )
            if match:
                indexed = self.state.job_index.ports_for(
                    principal, unquote(match.group(1)),
                )
        if requested.isdigit():
            port = int(requested)
            running = self.state.service_ports()
            # A cached job can outlive the service instance that created it.
            # Do not turn a stale/invalid port hint into a false 404; the
            # manager still owns the cross-port lookup and can find the job on
            # its currently running service.
            if port in running:
                return list(dict.fromkeys([*indexed, port]))
            return list(dict.fromkeys([*indexed, *running]))
        return list(dict.fromkeys([*indexed, *self.state.service_ports()]))

    def _service_port(self, parsed) -> int | None:
        requested = parse_qs(parsed.query).get("port", [""])[0]
        if requested.isdigit():
            value = int(requested)
            return value if value in self.state.service_ports() else None
        return self.state.preferred_service_port()

    def _service_route(self, parsed) -> ServiceRoute | None:
        query = parse_qs(parsed.query, keep_blank_values=True)
        raw_port = str(query.get("port", [""])[0] or "").strip()
        if raw_port and not raw_port.isdigit():
            json_response(
                self, {"success": False, "error": "port must be an integer"}, 400,
            )
            return None
        port = int(raw_port) if raw_port else None
        try:
            return self.state.route_for(
                port=port,
                server_id=str(query.get("server_id", [""])[0] or ""),
                branch=str(query.get("branch", [""])[0] or ""),
                feature=str(query.get("feature", [""])[0] or ""),
            )
        except TargetUnavailable as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
        except TargetNotFound as exc:
            json_response(self, {"success": False, "error": str(exc)}, 502)
        return None

    @staticmethod
    def _forwarded_service_path(parsed) -> str:
        manager_selector_keys = {"port", "server_id", "branch", "feature"}
        query = urlencode([
            (key, value) for key, value in parse_qsl(
                parsed.query, keep_blank_values=True,
            ) if key not in manager_selector_keys
        ])
        return parsed.path + (f"?{query}" if query else "")

    def _send_sqlite_web_response(self, response: ManagerSQLiteResponse) -> None:
        """Write a local sqlite-web WSGI response without a service-port header."""
        self.send_response(response.status)
        sent_content_length = False
        for key, value in response.headers:
            lowered = key.lower()
            if lowered in {"connection", "date", "server", "transfer-encoding"}:
                continue
            if lowered == "content-type":
                continue
            if lowered == "content-length":
                sent_content_length = True
                continue
            self.send_header(key, value)
        self.send_header("Content-Type", response.content_type)
        if not sent_content_length:
            self.send_header("Content-Length", str(len(response.body)))
        else:
            # The adapter materializes the response, so the actual length is
            # authoritative even if a middleware supplied a stale header.
            self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response.body)

    def _serve_sqlite_web(self, parsed, *, method: str) -> bool:
        """Serve `/sqlite-web` from Manager-owned state, never a worker port."""
        if not (
            parsed.path == "/sqlite-web"
            or parsed.path.startswith("/sqlite-web/")
        ):
            return False
        # The parent Manager route is a normal application tab.  Only the
        # embedded iframe (or a nested sqlite-web page reached from it) should
        # receive the database WSGI response; otherwise a browser refresh
        # would replace the Manager shell with raw sqlite-web HTML.
        if parsed.path in {"/sqlite-web", "/sqlite-web/"} and (
            parse_qs(parsed.query).get("presentation") != ["embedded"]
        ):
            return False
        session = self._session()
        # An embedded root without a Manager session must still render the
        # normal login shell.  Returning the JSON 401 body here makes a
        # WebView/tab show protocol data instead of the shared login UI.
        if session is None and parsed.path in {"/sqlite-web", "/sqlite-web/"}:
            return False
        if session is None:
            json_response(
                self, {"success": False, "error": "login required"}, 401,
            )
            return True
        body = b""
        if method in {"POST", "PUT", "PATCH"}:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except (TypeError, ValueError):
                json_response(
                    self, {"success": False, "error": "invalid request body"}, 400,
                )
                return True
            if length < 0 or length > 32 * 1024 * 1024:
                json_response(
                    self, {"success": False, "error": "invalid request body"}, 400,
                )
                return True
            body = self.rfile.read(length)
        try:
            response = self.state.sqlite_web.request(
                method=method,
                path=parsed.path,
                query=parsed.query,
                principal=str(session["username"]),
                headers={key: value for key, value in self.headers.items()},
                body=body,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            sys.stderr.write(f"[manager] sqlite-web failed: {exc}\n")
            json_response(
                self,
                {"success": False, "error": "manager database view unavailable"},
                503,
            )
            return True
        self._send_sqlite_web_response(response)
        return True

    def _proxy_service_get(self, parsed) -> bool:
        if not any(parsed.path.startswith(prefix) for prefix in _SERVICE_GET_PREFIXES):
            return False
        session = self._session()
        public_graph = (
            session is None and _PUBLIC_GRAPH_READ_RE.fullmatch(parsed.path)
        )
        public_docs = (
            parsed.path == "/docs"
            or parsed.path.startswith("/docs/")
            or parsed.path.startswith("/static/css/")
            or parsed.path.startswith("/static/js/")
            or parsed.path.startswith("/static/vendor/")
            or parsed.path.startswith("/static/images/")
        )
        if session is None and not (public_graph or public_docs):
            json_response(
                self, {"success": False, "error": "login required"}, 401,
            )
            return True
        route = self._service_route(parsed)
        if route is None:
            return True
        try:
            response = self.state.route_request(
                route,
                path=self._forwarded_service_path(parsed),
                principal=(
                    "__public_graph__" if public_graph
                    else "__public_docs__" if public_docs
                    else str(session["username"])
                ),
            )
        except (ConnectionError, ValueError):
            json_response(
                self, {"success": False, "error": "service port is unavailable"}, 502,
            )
            return True
        self._send_gateway_response(response, route=route)
        return True

    def _service_route_candidates(
        self, parsed,
    ) -> tuple[list[ServiceRoute], bool] | None:
        """Return online candidates while preserving explicit target intent."""
        query = parse_qs(parsed.query, keep_blank_values=True)
        raw_port = str(query.get("port", [""])[0] or "").strip()
        if raw_port and not raw_port.isdigit():
            json_response(
                self, {"success": False, "error": "port must be an integer"}, 400,
            )
            return None
        port = int(raw_port) if raw_port else None
        server_id = str(query.get("server_id", [""])[0] or "").strip()
        branch = str(query.get("branch", [""])[0] or "").strip()
        feature = str(query.get("feature", [""])[0] or "").strip()
        explicit = bool(server_id or raw_port or branch or feature)

        candidates = self.state.service_routes(include_offline=True)
        candidates = [
            route for route in candidates
            if (
                not server_id
                or server_id == "local" and not route.remote
                or route.server_id == server_id
            )
            and (port is None or route.port == port)
            and (not branch or route.branch == branch)
            and (not feature or feature in route.features)
        ]
        if not candidates:
            # Keep the legacy live-port seam used during bootstrap and in
            # tests where no Git worktree metadata is available.
            try:
                fallback = self.state.route_for(
                    port=port,
                    server_id=server_id,
                    branch=branch,
                    feature=feature,
                )
            except TargetUnavailable as exc:
                json_response(self, {"success": False, "error": str(exc)}, 503)
                return None
            except TargetNotFound as exc:
                json_response(self, {"success": False, "error": str(exc)}, 502)
                return None
            candidates = [fallback]

        online = [route for route in candidates if route.online]
        if not online:
            identity = server_id or branch or feature or (
                f"port {port}" if port is not None else "service target"
            )
            json_response(
                self,
                {"success": False, "error": f"target {identity} is offline"},
                503,
            )
            return None
        return sorted(online, key=self.state.route_selection_key), explicit

    @staticmethod
    def _gateway_json(response: GatewayResponse) -> dict[str, object]:
        try:
            value = response.json_object()
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _normalise_run_submission_identity(
        self,
        body: bytes,
        *,
        principal: str,
    ) -> bytes | None:
        """Validate and snapshot a locally owned Profile before forwarding."""
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            json_response(
                self,
                {"success": False, "error": "request body must be valid JSON"},
                400,
            )
            return None
        if not isinstance(value, dict):
            json_response(
                self,
                {"success": False, "error": "request body must be a JSON object"},
                400,
            )
            return None
        raw = str(value.get("acting_profile_ref") or "").strip()
        if not raw:
            # Preserve byte-for-byte forwarding for the ordinary user case;
            # existing API clients rely on this when signing request bodies.
            return body
        profile_id = raw.split(":", 1)[1] if raw.startswith("profile:") else raw
        profile_id = profile_id.strip()
        profiles = self.state.client_state.profiles(principal)
        selected = next(
            (
                item for item in profiles
                if str(item.get("profile_id") or "").strip() == profile_id
            ),
            None,
        )
        if selected is None:
            json_response(
                self,
                {
                    "success": False,
                    "error": "acting Profile does not belong to the current user",
                    "code": "acting_profile_not_owned",
                },
                403,
            )
            return None
        value["acting_profile_ref"] = f"profile:{profile_id}"
        value["acting_profile_name"] = str(
            selected.get("display_name") or profile_id
        ).strip()
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    def _capable_service_route(
        self,
        parsed,
        *,
        body: bytes,
        principal: str,
        content_type: str,
    ) -> ServiceRoute | None:
        """Select a route only after a read-only data-capability preflight."""
        candidates = self._service_route_candidates(parsed)
        if candidates is None:
            return None
        routes, explicit = candidates
        capability_failures: list[dict[str, object]] = []
        unavailable: list[dict[str, object]] = []
        requirements: list[dict[str, object]] = []
        for route in routes:
            try:
                response = self.state.route_request(
                    route,
                    path="/api/runs/capability-preview",
                    principal=principal,
                    method="POST",
                    body=body,
                    content_type=content_type,
                )
            except (ConnectionError, OSError, ValueError) as exc:
                unavailable.append({
                    "server_id": route.server_id,
                    "port": route.port,
                    "branch": route.branch,
                    "error": "service port is unavailable",
                    "detail": str(exc),
                })
                continue

            value = self._gateway_json(response)
            if 200 <= response.status < 300 and value.get("success", True):
                return route
            code = str(value.get("code") or "")
            if code == "data_capability_unavailable":
                candidate_requirements = value.get("requirements")
                if isinstance(candidate_requirements, list) and not requirements:
                    requirements = [
                        item for item in candidate_requirements
                        if isinstance(item, dict)
                    ]
                capability_failures.append({
                    "server_id": route.server_id,
                    "port": route.port,
                    "branch": route.branch,
                    "status": response.status,
                    "error": str(value.get("error") or "data capability unavailable"),
                })
                continue
            if response.status >= 500 or response.status == 404:
                unavailable.append({
                    "server_id": route.server_id,
                    "port": route.port,
                    "branch": route.branch,
                    "status": response.status,
                    "error": str(value.get("error") or "capability preflight unavailable"),
                })
                continue
            # The request itself is invalid (or the user is not authorised);
            # trying another server would only hide that client error.
            self._send_gateway_response(response, route=route)
            return None

        if capability_failures:
            json_response(self, {
                "success": False,
                "error": (
                    "no service target provides the requested "
                    "product, frequency, and data source"
                ),
                "code": "data_capability_unavailable",
                "requirements": requirements,
                "candidates": [*capability_failures, *unavailable],
                "explicit_target": explicit,
            }, 422)
            return None
        json_response(self, {
            "success": False,
            "error": "data capability preflight is unavailable",
            "code": "data_capability_preflight_unavailable",
            "candidates": unavailable,
            "explicit_target": explicit,
        }, 503)
        return None

    def _proxy_service_write(self, parsed, *, method: str) -> bool:
        patterns = _SERVICE_WRITE_PATTERNS.get(method, ())
        if not any(re.fullmatch(pattern, parsed.path) for pattern in patterns):
            return False
        session = self._session()
        if session is None:
            json_response(
                self, {"success": False, "error": "login required"}, 401,
            )
            return True
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1024 * 1024:
            json_response(
                self, {"success": False, "error": "invalid request body"}, 400,
            )
            return True
        body = self.rfile.read(length)
        content_type = str(self.headers.get("Content-Type") or "application/json")
        if method == "POST" and parsed.path == "/api/runs":
            body = self._normalise_run_submission_identity(
                body, principal=str(session["username"]),
            )
            if body is None:
                return True
        if method == "POST" and parsed.path == "/api/runs":
            route = self._capable_service_route(
                parsed,
                body=body,
                principal=str(session["username"]),
                content_type=content_type,
            )
        else:
            route = self._service_route(parsed)
        if route is None:
            return True
        try:
            response = self.state.route_request(
                route,
                path=self._forwarded_service_path(parsed),
                principal=str(session["username"]),
                method=method,
                body=body,
                content_type=content_type,
                origin_server_id=(
                    self.state.server_id
                    if method == "POST" and parsed.path == "/api/runs"
                    else ""
                ),
            )
        except (ConnectionError, ValueError):
            json_response(
                self, {"success": False, "error": "service port is unavailable"}, 502,
            )
            return True
        if method == "POST" and parsed.path == "/api/runs":
            self.state.record_run_submission(
                response,
                principal=str(session["username"]),
                route=route,
                origin_server_id=self.state.server_id,
            )
        self._send_gateway_response(response, route=route)
        return True

    def _send_gateway_response(
        self,
        response: GatewayResponse,
        *,
        port: int | None = None,
        route: ServiceRoute | None = None,
    ) -> None:
        selected_port = int(route.port if route is not None else (port or 0))
        body = response.body
        content_type = response.content_type
        if content_type == "application/json":
            try:
                value = response.json_object()
                value.setdefault("port", selected_port)
                body = json.dumps(value, ensure_ascii=False).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
                pass
        self.send_response(response.status)
        self.send_header("Content-Type", content_type)
        if response.content_disposition:
            self.send_header(
                "Content-Disposition", response.content_disposition,
            )
        if response.etag:
            self.send_header("ETag", response.etag)
        self.send_header("X-FactorTester-Service-Port", str(selected_port))
        if route is not None:
            self.send_header("X-FactorTester-Service-Server", route.server_id)
            if route.branch:
                self.send_header("X-FactorTester-Service-Branch", route.branch)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _job_routes(self, parsed, principal: str | None = None) -> list[ServiceRoute]:
        """Resolve job origins, using peer Managers when federation is active."""
        query = parse_qs(parsed.query, keep_blank_values=True)
        raw_port = str(query.get("port", [""])[0] or "").strip()
        if raw_port and not raw_port.isdigit():
            raise ValueError("port must be an integer")
        port = int(raw_port) if raw_port else None
        server_id = str(query.get("server_id", [""])[0] or "").strip()
        branch = str(query.get("branch", [""])[0] or "").strip()
        feature = str(query.get("feature", [""])[0] or "").strip()
        explicit = bool(server_id or branch or feature or port is not None)
        has_peers = bool(
            self.state.federation_registry.servers(include_offline=True)
        )
        if explicit:
            return [self.state.route_for(
                port=port,
                server_id=server_id,
                branch=branch,
                feature=feature,
            )]
        if has_peers:
            routes = self.state.service_routes(include_offline=True)
            offline_remote = [
                route for route in routes if route.remote and not route.online
            ]
            if offline_remote:
                names = ", ".join(
                    f"{route.server_id}:{route.port}" for route in offline_remote
                )
                raise TargetUnavailable(f"registered target is offline: {names}")
            online = [route for route in routes if route.online]
            if not online:
                raise TargetUnavailable("no online service target")
            return sorted(online, key=self.state.route_selection_key)
        # Preserve the legacy manager test seam and local cached origins when
        # no peer Manager has been registered yet.
        return [
            self.state._local_route(port=value, online=True)
            for value in self._job_ports(parsed, principal)
        ]

    def _artifact_ticket_for_route(
        self,
        route: ServiceRoute,
        *,
        job_id: str,
        name: str,
        principal: str,
        preview: bool,
        archive: bool = False,
    ) -> dict[str, object]:
        if route.remote:
            return self.state.federation_gateway.artifact_ticket(
                route,
                job_id=job_id,
                name=name,
                principal=principal,
                preview=preview,
                archive=archive,
            )
        from server.jobs.repository import JobRepository

        repository = JobRepository()
        job = repository.load(job_id)
        if job is None or (
            principal != "__public_jobs__" and job.owner != principal
        ):
            raise KeyError("artifact was not found")
        if archive:
            name = "__archive__"
        else:
            metadata = repository.load_artifact(
                job_id=job_id,
                name=name,
                owner=job.owner,
            )
            if metadata is None or str(metadata.get("state") or "") != "active":
                raise KeyError("artifact was not found")
            if (
                principal == "__public_jobs__"
                and str(metadata.get("artifact_role") or "output") == "input"
            ):
                raise PermissionError("登录后才能查看运行输入")
        ticket = self.state.artifact_ticket_codec().issue(
            owner=job.owner,
            job_id=job_id,
            name=name,
            server_id=self.state.server_id,
            preview=preview,
        )
        endpoint = route.artifact_endpoint or artifact_data_endpoint(
            endpoint=route.endpoint or "http://127.0.0.1:7998",
            port=route.artifact_port or artifact_data_port(),
        )
        return {
            "success": True,
            "ticket": ticket,
            "data_endpoint": endpoint,
            "url": artifact_data_url(
                endpoint,
                job_id=job_id,
                name=name,
                ticket=ticket,
            ),
        }

    def _redirect_artifact_to_data_plane(
        self,
        parsed,
        *,
        job_id: str,
        name: str,
        principal: str,
        preview: bool,
        archive: bool = False,
    ) -> bool:
        try:
            routes = self._job_routes(parsed, principal)
        except TargetUnavailable as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return True
        except (TargetNotFound, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 502)
            return True
        for route in routes:
            try:
                value = self._artifact_ticket_for_route(
                    route,
                    job_id=job_id,
                    name=name,
                    principal=principal,
                    preview=preview,
                    archive=archive,
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 401)
                return True
            except (ConnectionError, KeyError, OSError, ValueError, ArtifactTicketError):
                continue
            url = str(value.get("url") or "").strip()
            if not url:
                continue
            self.send_response(307)
            self.send_header("Location", url)
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "X-FactorTester-Artifact-Data-Port",
                str(route.artifact_port or artifact_data_port()),
            )
            self.send_header("Content-Length", "0")
            self.end_headers()
            return True
        # Compatibility fallback: a separately supervised/older service may
        # not have the 7997 data plane yet.  The normal service gateway can
        # still return the artifact, while new Managers use the redirect
        # above and keep large files off the 7998 control-plane hop.
        return False

    def _proxy_job_request(self, parsed, *, method: str) -> bool:
        match = re.fullmatch(
            r"/api/jobs/([A-Za-z0-9._-]{1,128})"
            r"(/result|/artifacts(?:/archive|/[^/]{1,512}(?:/preview)?)?"
            r"|/group-detail|/group-ranking-detail|/group-snapshot"
            r"|/group-order-flow)?",
            parsed.path,
        )
        if match is None:
            return False
        suffix = match.group(2) or ""
        if method == "POST" and (
            suffix != "/artifacts/generate"
            and suffix not in _JOB_ANALYSIS_PATHS
        ):
            return False
        session = self._session()
        suffix_value = suffix
        public = (
            session is None
            and method == "GET"
            and (suffix_value in {"", "/result", "/artifacts"}
                 or suffix_value.endswith("/preview"))
        )
        if session is None and not public:
            json_response(
                self, {"success": False, "error": "login required"}, 401,
            )
            return True
        if public:
            principal = "__public_jobs__"
        else:
            principal = str(session["username"])
        job_id = quote(unquote(match.group(1)), safe="")
        if ".." in unquote(suffix).split("/"):
            json_response(
                self, {"success": False, "error": "invalid artifact name"}, 400,
            )
            return True
        artifact_match = re.fullmatch(
            r"/artifacts/([^/]+)(/preview)?", suffix,
        )
        archive = suffix == "/artifacts/archive"
        if method == "GET" and (artifact_match is not None or archive):
            redirected = self._redirect_artifact_to_data_plane(
                parsed,
                job_id=unquote(match.group(1)),
                name=(
                    "__archive__" if archive
                    else unquote(artifact_match.group(1))
                ),
                principal=principal,
                preview=bool(artifact_match and artifact_match.group(2)),
                archive=archive,
            )
            if redirected:
                return True
        path = _JOB_ANALYSIS_PATHS.get(suffix, f"/api/jobs/{job_id}{suffix}")
        forwarded: dict[str, object] = {}
        if method == "POST":
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except (TypeError, ValueError):
                length = 0
            if length <= 0 or length > 1024 * 1024:
                json_response(
                    self, {"success": False, "error": "invalid request body"}, 400,
                )
                return True
            body = self.rfile.read(length)
            if suffix in _JOB_ANALYSIS_PATHS:
                try:
                    payload = json.loads(body)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    json_response(
                        self, {"success": False, "error": "invalid request body"}, 400,
                    )
                    return True
                if not isinstance(payload, dict):
                    json_response(
                        self, {"success": False, "error": "invalid request body"}, 400,
                    )
                    return True
                payload["job_id"] = unquote(match.group(1))
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            forwarded = {
                "body": body,
                "content_type": str(
                    self.headers.get("Content-Type") or "application/json"
                ),
            }
        try:
            routes = self._job_routes(parsed, principal)
        except TargetUnavailable as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return True
        except (TargetNotFound, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 502)
            return True
        last_response: tuple[ServiceRoute, GatewayResponse] | None = None
        for route in routes:
            try:
                response = self.state.route_request(
                    route,
                    path=path,
                    principal=principal,
                    method=method,
                    **forwarded,
                )
            except (ConnectionError, ValueError):
                continue
            last_response = (route, response)
            if response.status == 404:
                continue
            self._send_gateway_response(response, route=route)
            return True
        if last_response is not None:
            self._send_gateway_response(
                last_response[1],
                route=last_response[0],
            )
            return True
        json_response(
            self, {"success": False, "error": "job was not found"}, 404,
        )
        return True

    def _proxy_job_stream(self, parsed) -> bool:
        match = re.fullmatch(
            r"/api/jobs/([A-Za-z0-9._-]{1,128})/stream", parsed.path,
        )
        if match is None:
            return False
        session = self._session()
        public = session is None
        principal = "__public_jobs__" if public else str(session["username"])
        path = self._forwarded_service_path(parsed)
        job_id = unquote(match.group(1))
        last_error: HTTPError | None = None
        connection_failed = False
        try:
            routes = self._job_routes(parsed, principal)
        except TargetUnavailable as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return True
        except (TargetNotFound, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 502)
            return True
        for route in routes:
            try:
                if route.remote:
                    upstream = self.state.federation_gateway.open_stream(
                        route,
                        path=path,
                        principal=principal,
                        last_event_id=str(self.headers.get("Last-Event-ID") or ""),
                    )
                else:
                    request = Request(
                        f"http://127.0.0.1:{route.port}{path}",
                        headers={
                            "Accept": "text/event-stream",
                            "X-FactorTester-Principal": principal,
                            "X-FactorTester-Manager": self.state.capability_token(),
                            "Last-Event-ID": str(self.headers.get("Last-Event-ID") or ""),
                        },
                    )
                    upstream = urlopen(request, timeout=15)
            except HTTPError as exc:
                last_error = exc
                if exc.code == 404:
                    continue
                body = exc.read()
                self.send_response(exc.code)
                self.send_header("Content-Type", exc.headers.get_content_type())
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return True
            except (ConnectionError, OSError, URLError):
                connection_failed = True
                continue
            with upstream:
                self.send_response(upstream.status)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("X-FactorTester-Service-Port", str(route.port))
                self.send_header("X-FactorTester-Service-Server", route.server_id)
                if route.branch:
                    self.send_header("X-FactorTester-Service-Branch", route.branch)
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    event_buffer = b""
                    while chunk := upstream.read(4096):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        event_buffer = (event_buffer + chunk).replace(b"\r\n", b"\n")
                        while b"\n\n" in event_buffer:
                            frame, event_buffer = event_buffer.split(b"\n\n", 1)
                            data = b"\n".join(
                                line[5:].strip()
                                for line in frame.splitlines()
                                if line.startswith(b"data:")
                            )
                            if not data:
                                continue
                            try:
                                event = json.loads(data.decode("utf-8"))
                            except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
                                continue
                            if isinstance(event, dict):
                                self.state.job_index.upsert(principal, [{
                                    **event,
                                    "job_id": str(event.get("job_id") or job_id),
                                    "port": route.port,
                                    "service_port": route.port,
                                    "server_id": route.server_id,
                                    "server_endpoint": route.endpoint,
                                    "server_host": urlparse(route.endpoint).hostname or "",
                                    "server_role": route.role,
                                    "server_branch": route.branch,
                                    "server_revision": route.revision,
                                    "updated_at": str(event.get("updated_at") or time.time()),
                                }], emit_events=not route.remote)
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    pass
                return True
        if last_error is not None:
            body = last_error.read()
            self.send_response(last_error.code)
            self.send_header("Content-Type", last_error.headers.get_content_type())
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        if connection_failed:
            json_response(
                self,
                {"success": False, "error": "job stream service is unavailable"},
                503,
            )
            return True
        json_response(
            self, {"success": False, "error": "job stream was not found"}, 404,
        )
        return True

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/compliance":
            requested = parse_qs(parsed.query, keep_blank_values=True).get(
                "next", ["/"]
            )[0]
            self._serve_compliance_page(str(requested or "/"))
            return
        if parsed.path == "/device-gate":
            requested = parse_qs(parsed.query, keep_blank_values=True).get(
                "next", ["/"]
            )[0]
            self._serve_device_gate(str(requested or "/"))
            return
        if parsed.path == "/login":
            self._serve_login_page(parsed)
            return
        if parsed.path == "/device-authorize":
            if not self._public_login_gate(parsed, method="GET"):
                return
            self._device_authorization_page(parsed)
            return
        if not self._public_login_gate(parsed, method="GET"):
            return
        if parsed.path == "/api/devices":
            self._device_list()
            return
        if parsed.path == "/api/device/summary":
            self._device_summary()
            return
        if parsed.path == "/api/device/public-targets":
            self._device_public_targets()
            return
        if parsed.path == "/api/server/network-info":
            self._server_network_info()
            return
        if parsed.path == "/api/federation/servers":
            self._federation_servers()
            return
        if parsed.path == "/api/federation/config":
            self._federation_config()
            return
        if parsed.path == "/api/client-assets/revision":
            json_response(
                self,
                {"success": True, "revision": asset_revision()},
                headers={"Cache-Control": "no-store"},
            )
            return
        locale_match = re.fullmatch(
            r"/api/localizations/(zh-Hans|en)", parsed.path,
        )
        if locale_match:
            try:
                value = web_localization(
                    _REPO_ROOT / "apple/Resources/Shared/Localizable.xcstrings",
                    locale_match.group(1),
                )
            except (OSError, ValueError, json.JSONDecodeError):
                json_response(self, {"success": False, "error": "localization catalog is unavailable"}, 503)
                return
            json_response(self, value)
            return
        if parsed.path.startswith("/research-static/"):
            try:
                body, content_type = static_file(
                    parsed.path.removeprefix("/research-static/"),
                )
            except ValueError:
                self.send_error(404)
                return
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
            return
        if parsed.path == "/static/config/modules.json":
            try:
                body = (_REPO_ROOT / "static/config/modules.json").read_bytes()
                json.loads(body.decode("utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                json_response(
                    self,
                    {"success": False, "error": "module manifest is unavailable"},
                    503,
                )
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self._serve_client_release(parsed.path):
            return
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
            return
        if parsed.path == "/api/jobs/ports":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            payload = {
                "ports": self.state.service_ports(),
                "automatic_port": self.state.preferred_service_port(),
            }
            if self.state.has_federated_servers():
                payload["targets"] = [
                    route.as_dict()
                    for route in self.state.service_routes(include_offline=True)
                ]
            json_response(self, payload)
            return
        if parsed.path == "/api/jobs":
            session = self._session()
            query = parse_qs(parsed.query, keep_blank_values=True)
            scope = str(query.get("scope", [""])[0] or "").strip().lower()
            if not scope:
                if session is None or str(session.get("role") or "") == "super_admin":
                    scope = "server"
                else:
                    scope = "mine"
            if session is None and scope != "server":
                # Keep the three scopes visible in the web client without
                # asking an anonymous request to discover private accounts.
                json_response(self, {
                    "success": True,
                    "scope": scope,
                    "requires_login": True,
                    "jobs": [],
                    "page": 1,
                    "page_size": 20,
                    "total": 0,
                    "total_pages": 1,
                    "has_more": False,
                    "next_cursor": None,
                })
                return
            try:
                limit = int(query.get("limit", ["20"])[0] or 20)
            except (TypeError, ValueError):
                json_response(self, {
                    "success": False,
                    "error": "limit 必须是整数",
                }, 400)
                return
            if session is None:
                limit = min(limit, 20)
                principal = "__public_jobs__"
            else:
                principal = str(session["username"])
            if scope == "cross-server":
                if session is None:
                    json_response(self, {
                        "success": True,
                        "scope": scope,
                        "requires_login": True,
                        "jobs": [],
                        "page": 1,
                        "page_size": 20,
                        "total": 0,
                        "total_pages": 1,
                        "has_more": False,
                        "next_cursor": None,
                    })
                    return
                try:
                    requested_page = max(
                        1, int(query.get("page", ["1"])[0] or 1),
                    )
                    source_scope = str(
                        query.get("source_scope", [""])[0] or ""
                    ).strip().lower()
                except (TypeError, ValueError):
                    json_response(self, {
                        "success": False,
                        "error": "page 必须是整数",
                    }, 400)
                    return
                if not source_scope:
                    source_scope = (
                        "server"
                        if str(session.get("role") or "") == "super_admin"
                        else "mine"
                    )
                if source_scope == "server" and str(
                    session.get("role") or ""
                ) != "super_admin":
                    json_response(self, {
                        "success": False,
                        "error": "只有超级管理员可以查看跨服务器全部任务",
                    }, 403)
                    return
                try:
                    payload = self.state.aggregate_cross_server_jobs(
                        principal=principal,
                        page=requested_page,
                        limit=limit,
                        source_scope=source_scope,
                    )
                except (ConnectionError, OSError, TypeError, ValueError) as exc:
                    json_response(self, {
                        "success": False,
                        "error": str(exc),
                    }, 503)
                    return
                payload["success"] = True
                payload["scope"] = scope
                json_response(self, payload)
                return
            if scope == "server":
                # Server history is a public projection backed by the shared
                # job repository.  Keep its cache fallback so a stale
                # service process cannot turn the whole task page into 502.
                cursor = str(query.get("cursor", [""])[0] or "")
                try:
                    if session is not None and str(session.get("role") or "") == "super_admin":
                        payload = self.state.aggregate_server_jobs(
                            principal=principal, cursor=cursor, limit=limit,
                        )
                    else:
                        payload = self.state.aggregate_public_jobs(
                            cursor=cursor, limit=limit,
                        )
                except TargetUnavailable as exc:
                    json_response(self, {"success": False, "error": str(exc)}, 503)
                    return
                except (ConnectionError, OSError, ValueError) as exc:
                    json_response(self, {"success": False, "error": str(exc)}, 503)
                    return
                payload.setdefault("success", True)
                payload.setdefault("scope", scope)
                fallback_port = None
                for item in payload.get("jobs") or ():
                    if isinstance(item, dict):
                        if "port" not in item:
                            if fallback_port is None:
                                fallback_port = self.state.preferred_service_port() or 0
                            item["port"] = fallback_port
                json_response(self, payload)
                return
            try:
                requested_page = max(1, int(query.get("page", ["1"])[0] or 1))
            except (TypeError, ValueError):
                json_response(self, {
                    "success": False, "error": "page 必须是整数",
                }, 400)
                return
            try:
                if scope == "mine":
                    payload = self.state.aggregate_account_jobs(
                        principal=principal,
                        scope=scope,
                        page=requested_page,
                        limit=limit,
                    )
                elif scope == "subordinates":
                    users = _manager_subordinate_users(principal)
                    requested_user = str(
                        query.get("username", query.get("user", [""]))[0] or "",
                    ).strip()
                    base = {
                        "success": True,
                        "scope": scope,
                        "users": users,
                    }
                    if not requested_user:
                        json_response(self, {
                            **base,
                            "selection_required": True,
                            "jobs": [],
                            "page": 1,
                            "page_size": 20,
                            "total": 0,
                            "total_pages": 1,
                            "has_more": False,
                            "next_cursor": None,
                        })
                        return
                    allowed = {item["username"] for item in users}
                    if requested_user not in allowed:
                        json_response(self, {
                            "success": False, "error": "无权查看该下级用户任务",
                        }, 403)
                        return
                    payload = self.state.aggregate_account_jobs(
                        principal=principal,
                        scope=scope,
                        username=requested_user,
                        page=requested_page,
                        limit=limit,
                    )
                    payload["users"] = users
                else:
                    json_response(self, {
                        "success": False, "error": "不支持的任务范围",
                    }, 400)
                    return
            except TargetUnavailable as exc:
                json_response(self, {"success": False, "error": str(exc)}, 503)
                return
            except (ConnectionError, OSError, ValueError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 503)
                return
            payload["success"] = True
            payload["scope"] = scope
            json_response(self, payload)
            return
        if self._serve_manager_application(parsed, method="GET"):
            return
        if self._proxy_job_stream(parsed):
            return
        if self._proxy_job_request(parsed, method="GET"):
            return
        if parsed.path == "/api/client/profiles":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            json_response(self, {
                "profiles": self.state.client_state.profiles(
                    str(session["username"]),
                ),
            })
            return
        if parsed.path == "/api/client/workspace":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            json_response(self, {
                "workspace": self.state.client_state.workspace(
                    str(session["username"]),
                ),
            })
            return
        if parsed.path == "/api/client/research":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            json_response(self, {
                "success": True,
                "research": self.state.client_state.local_research(
                    str(session["username"]),
                ),
            })
            return
        local_research_resource_match = re.fullmatch(
            r"/api/client/research/([^/]+)/local-resources/([a-f0-9]{24})",
            parsed.path,
        )
        if local_research_resource_match:
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            try:
                raw, content_type, filename = self.state.client_state.local_research_resource(
                    str(session["username"]),
                    unquote(local_research_resource_match.group(1)),
                    local_research_resource_match.group(2),
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except (OSError, ValueError, KeyError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return
            safe_filename = re.sub(
                r"[^A-Za-z0-9._-]", "_", Path(filename).name,
            ) or "resource"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            disposition = (
                "inline" if parse_qs(parsed.query).get("inline") == ["1"]
                else "attachment"
            )
            self.send_header(
                "Content-Disposition", f'{disposition}; filename="{safe_filename}"',
            )
            self.send_header("Cache-Control", "private, no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        local_research_asset_match = re.fullmatch(
            r"/api/client/research/([^/]+)/assets/([a-f0-9]{24})",
            parsed.path,
        )
        if local_research_asset_match:
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            try:
                raw, content_type, filename = self.state.client_state.local_research_asset(
                    str(session["username"]),
                    unquote(local_research_asset_match.group(1)),
                    local_research_asset_match.group(2),
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except (OSError, ValueError, KeyError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return
            safe_filename = re.sub(
                r"[^A-Za-z0-9._-]", "_", Path(filename).name,
            ) or "asset"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header(
                "Content-Disposition", f'inline; filename="{safe_filename}"',
            )
            self.send_header("Cache-Control", "private, no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        local_research_component_match = re.fullmatch(
            r"/api/client/research/([^/]+)/chapters/([^/]+)/components/([^/]+)",
            parsed.path,
        )
        if local_research_component_match:
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            try:
                value = self.state.client_state.local_research_component(
                    str(session["username"]),
                    unquote(local_research_component_match.group(1)),
                    unquote(local_research_component_match.group(2)),
                    unquote(local_research_component_match.group(3)),
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except (OSError, ValueError, KeyError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return
            json_response(self, {"success": True, **value})
            return
        local_research_chapter_match = re.fullmatch(
            r"/api/client/research/([^/]+)/(index|chapters/[^/]+)", parsed.path,
        )
        if local_research_chapter_match:
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            local_ref = unquote(local_research_chapter_match.group(1))
            suffix = local_research_chapter_match.group(2)
            try:
                if suffix == "index":
                    value = self.state.client_state.local_research_index(
                        str(session["username"]), local_ref,
                    )
                else:
                    chapter_id = unquote(suffix.split("/", 1)[1])
                    value = self.state.client_state.local_research_chapter(
                        str(session["username"]), local_ref, chapter_id,
                        include_content=parse_qs(parsed.query).get("metadata") != ["1"],
                    )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except (OSError, ValueError, KeyError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return
            json_response(self, {"success": True, **value})
            return
        local_research_match = re.fullmatch(
            r"/api/client/research/([^/]+)", parsed.path,
        )
        if local_research_match:
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            try:
                value = self.state.client_state.local_research_report(
                    str(session["username"]),
                    unquote(local_research_match.group(1)),
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except (OSError, ValueError, KeyError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return
            json_response(self, {"success": True, **value})
            return
        if parsed.path == "/api/client/preferences":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            json_response(self, {
                "preferences": self.state.user_preferences.read(
                    str(session["username"]),
                ),
            })
            return
        if self._serve_sqlite_web(parsed, method="GET"):
            return
        if self._proxy_service_get(parsed):
            return
        if parsed.path == "/api/public-research":
            session = self._session()
            viewer = str(session["username"]) if session else None
            json_response(self, {
                "reports": self.state.public_research.list_visible(viewer),
            })
            return
        public_component_match = re.fullmatch(
            r"/api/public-research/([A-Za-z0-9_-]{20,64})/chapters/([^/]+)/components/([^/]+)",
            parsed.path,
        )
        if public_component_match:
            session = self._session()
            viewer = str(session["username"]) if session else None
            try:
                value = self.state.public_research.component(
                    public_component_match.group(1),
                    unquote(public_component_match.group(2)),
                    unquote(public_component_match.group(3)),
                    viewer,
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return
            json_response(self, {"success": True, **value})
            return
        public_chapter_match = re.fullmatch(
            r"/api/public-research/([A-Za-z0-9_-]{20,64})/(index|chapters/[A-Za-z0-9_.:-]{1,256})",
            parsed.path,
        )
        if public_chapter_match:
            session = self._session()
            viewer = str(session["username"]) if session else None
            try:
                publication_id = public_chapter_match.group(1)
                suffix = public_chapter_match.group(2)
                if suffix == "index":
                    value = self.state.public_research.index(publication_id, viewer)
                else:
                    value = self.state.public_research.chapter(
                        publication_id, unquote(suffix.split("/", 1)[1]), viewer,
                        include_content=parse_qs(parsed.query).get("metadata") != ["1"],
                    )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return
            json_response(self, {"success": True, **value})
            return
        public_match = re.fullmatch(
            r"/api/public-research/([A-Za-z0-9_-]{20,64})", parsed.path,
        )
        if public_match:
            session = self._session()
            viewer = str(session["username"]) if session else None
            try:
                value = self.state.public_research.projection(
                    public_match.group(1), viewer,
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return
            etag = '"' + str(value["projection_hash"]) + '"'
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.end_headers()
                return
            self.send_response(200)
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "private, no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        asset_match = re.fullmatch(
            r"/api/public-research/([A-Za-z0-9_-]{20,64})/assets/([A-Za-z0-9_-]{8,64})",
            parsed.path,
        )
        if asset_match:
            session = self._session()
            viewer = str(session["username"]) if session else None
            try:
                raw, content_type, filename = self.state.public_research.asset(
                    asset_match.group(1), asset_match.group(2), viewer,
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'inline; filename="{filename}"')
            self.send_header("Cache-Control", "private, no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        local_resource_match = re.fullmatch(
            r"/api/public-research/([A-Za-z0-9_-]{20,64})/local-resources/([a-f0-9]{24})",
            parsed.path,
        )
        if local_resource_match:
            session = self._session()
            viewer = str(session["username"]) if session else None
            try:
                raw, content_type, filename = self.state.public_research.local_resource(
                    local_resource_match.group(1), local_resource_match.group(2), viewer,
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return
            safe_filename = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name) or "resource"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            disposition = "inline" if parse_qs(parsed.query).get("inline") == ["1"] else "attachment"
            self.send_header("Content-Disposition", f'{disposition}; filename="{safe_filename}"')
            self.send_header("Cache-Control", "private, no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        attachment_match = re.fullmatch(
            r"/api/public-research/([A-Za-z0-9_-]{20,64})/attachments/(?:attachment%3Asha256%3A|attachment:sha256:)?([a-f0-9]{64})",
            parsed.path,
        )
        if attachment_match:
            session = self._session()
            viewer = str(session["username"]) if session else None
            try:
                raw, content_type, filename = self.state.public_research.attachment(
                    attachment_match.group(1),
                    f"attachment:sha256:{attachment_match.group(2)}",
                    viewer,
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "private, no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if parsed.path == "/api/research-publications/settings":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            json_response(self, {
                "reports": self.state.public_research.list_owner(
                    str(session["username"]),
                ),
            })
            return
        if parsed.path == "/api/session":
            session = self.state.session(self._bearer_token())
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            json_response(self, {"success": True, **session})
            return
        if parsed.path == "/api/worktrees":
            if not self._has_api_authorization():
                self._require_capability()
                return
            data = [
                {
                    "instance_id": self.state.instance_id(wt),
                    "label": wt.label,
                    "branch": wt.branch,
                    "head": wt.head,
                    "port": wt.port,
                    "running": self.state.is_running(wt.path),
                    "daemon_running": self.state.daemon_running(wt.path),
                    "port_in_use": port_in_use(wt.port),
                }
                for wt in self.state.worktrees()
            ]
            json_response(self, {
                "worktrees": data,
                "manager": {
                    "loopback_ip": "127.0.0.1",
                    "lan_ip": _lan_ip(),
                    "release_root": str(self.state.release_root),
                },
                "vibe_trading": {
                    "instance_id": "service-vibe-trading",
                    "port": VIBE_TRADING_PORT,
                    "running": self.state.vibe_running(),
                    "port_in_use": port_in_use(VIBE_TRADING_PORT),
                },
            })
            return
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
            return
        if parsed.path != "/manager-legacy":
            self.send_error(404)
            return
        if not self._is_loopback_client():
            json_response(self, {"success": False, "error": "localhost required"}, 403)
            return
        message = parse_qs(parsed.query).get("message", [""])[0]
        body = page(self.state, message)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        # Authentication is the one public POST route in the protected
        # instance.  Registration itself is rejected by _register when the
        # server disables public account creation.
        if parsed.path == "/auth/login":
            self._login()
            return
        if parsed.path == "/auth/register":
            self._register()
            return
        if not self._public_login_gate(parsed, method="POST"):
            return
        if parsed.path == "/api/device/challenge":
            self._device_challenge()
            return
        if parsed.path == "/api/device/verify":
            self._device_verify()
            return
        if parsed.path == "/api/device/authorization/redeem":
            self._device_authorization_redeem()
            return
        if parsed.path == "/api/device/authorization":
            self._device_authorization_create()
            return
        if parsed.path == "/api/devices/enroll":
            self._device_enroll()
            return
        if parsed.path == "/api/devices/revoke":
            self._device_revoke()
            return
        if parsed.path == "/api/federation/register":
            self._federation_register()
            return
        if parsed.path == "/api/federation/sync/events":
            self._federation_sync_events()
            return
        if parsed.path == "/api/federation/jobs/query":
            self._federation_jobs_query()
            return
        if parsed.path == "/api/federation/sync/reconcile":
            self._federation_sync_reconcile()
            return
        if parsed.path == "/api/federation/sync":
            self._federation_sync()
            return
        if parsed.path == "/api/federation/artifact-ticket":
            self._federation_artifact_ticket()
            return
        if parsed.path == "/api/federation/proxy":
            self._federation_proxy()
            return
        if parsed.path == "/api/federation/stream":
            self._federation_stream()
            return
        if parsed.path == "/api/federation/capabilities":
            self._federation_capabilities()
            return
        if self._serve_sqlite_web(parsed, method="POST"):
            return
        if self.path == "/auth/logout":
            token = self._bearer_token()
            if self.state.session_principal(token) is None:
                self._require_capability()
                return
            self.state.logout(token)
            json_response(
                self,
                {"success": True},
                headers={"Set-Cookie": self._session_cookie(token, clear=True)},
            )
            return
        if self._serve_manager_application(parsed, method="POST"):
            return
        if self._proxy_job_request(parsed, method="POST"):
            return
        if self.path == "/api/public-research/sync":
            if not self._is_loopback_client():
                json_response(self, {"success": False, "error": "local FTClient required"}, 403)
                return
            try:
                value = self.state.public_research.sync(self._json_body(32 * 1024 * 1024))
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
                return
            json_response(self, {"success": True, **value})
            return
        if self.path == "/api/public-research/publish":
            if not self._is_loopback_client():
                json_response(self, {"success": False, "error": "local FTClient required"}, 403)
                return
            try:
                payload = self._json_body(32 * 1024 * 1024)
                projection = payload.get("projection")
                report_id = str(payload.get("report_id") or "")
                owner_ref = str(payload.get("owner_ref") or "")
                if isinstance(projection, dict) and str(payload.get("public_title") or "").strip():
                    projection = {
                        **projection,
                        "title": str(payload["public_title"]).strip(),
                    }
                    # The title is part of the content-addressed projection.
                    # Recompute the hash after the optional public override so
                    # the list ETag and the mirrored payload describe the same
                    # bytes instead of retaining the local title's hash.
                    projection["projection_hash"] = hashlib.sha256(
                        json.dumps(
                            {
                                key: value
                                for key, value in projection.items()
                                if key != "projection_hash"
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()
                synced = self.state.public_research.sync({
                    "report_id": report_id,
                    "owner_ref": owner_ref,
                    "profile_ref": str(payload.get("profile_ref") or ""),
                    "projection": projection,
                })
                if synced.get("status") != "synced":
                    json_response(self, {"success": False, **synced}, 409)
                    return
                settings = self.state.public_research.configure(
                    owner_ref=owner_ref,
                    report_id=report_id,
                    projection=None,
                    visibility="public",
                    auto_sync=True,
                    relay_local_files=False,
                    authorized_users=[],
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except (TypeError, ValueError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
                return
            json_response(self, {
                "success": True,
                "status": "published",
                "publication_id": settings["publication_id"],
                "report_id": settings["report_id"],
                "visibility": settings["visibility"],
                "generation": settings.get("generation"),
                "projection_hash": projection["projection_hash"],
            })
            return
        if self.path == "/api/public-research/revoke":
            if not self._is_loopback_client():
                json_response(self, {"success": False, "error": "local FTClient required"}, 403)
                return
            try:
                payload = self._json_body(64 * 1024)
                value = self.state.public_research.revoke_publication(
                    str(payload.get("publication_id") or ""),
                )
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return
            json_response(self, {"success": True, **value})
            return
        if self.path == "/api/research-publications/settings":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            try:
                payload = self._json_body(256 * 1024)
                value = self.state.public_research.configure(
                    owner_ref=str(session["username"]),
                    report_id=str(payload.get("report_id") or ""),
                    projection=None,
                    visibility=str(payload.get("visibility") or "private"),
                    auto_sync=bool(payload.get("auto_sync", True)),
                    relay_local_files=bool(payload.get("relay_local_files", False)),
                    authorized_users=list(payload.get("authorized_users") or []),
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except (TypeError, ValueError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
                return
            json_response(self, {"success": True, "settings": value})
            return
        if self.path == "/api/client/preferences":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            try:
                value = self.state.user_preferences.update(
                    str(session["username"]),
                    self._json_body(64 * 1024),
                )
            except (TypeError, ValueError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
                return
            json_response(self, {"success": True, "preferences": value})
            return
        if self._proxy_service_write(parsed, method="POST"):
            return
        actions = {
            "/vibe/start",
            "/vibe/stop",
            "/start",
            "/stop",
            "/restart-api",
            "/restart-bundle",
            "/force-stop",
        }
        if self.path not in actions:
            self.send_error(404)
            return
        if not (
            self._has_api_authorization()
            or self._is_same_origin_browser_action()
        ):
            self._require_capability()
            return
        length = int(self.headers.get("Content-Length", "0"))
        params = parse_qs(self.rfile.read(length).decode("utf-8"))
        if set(params) != {"instance_id"} or len(params["instance_id"]) != 1:
            json_response(
                self,
                {"success": False, "error": "instance_id is required and is the only accepted target"},
                400,
            )
            return
        instance_id = str(params["instance_id"][0])
        try:
            operation = self._resolve_operation(instance_id)
        except LookupError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 404)
            return
        if self.headers.get("Prefer", "").strip().lower() == "respond-async":
            json_response(self, {
                "success": True,
                "submitted": True,
                "instance_id": instance_id,
            }, 202)
            self.state.submit_action(operation, f"{self.path} {instance_id}")
            return
        try:
            message = operation()
        except Exception as exc:
            sys.stderr.write(f"[manager] action {self.path} failed: {exc}\n")
            json_response(
                self,
                {"success": False, "error": "manager action failed"},
                409,
            )
            return
        json_response(self, {
            "success": True,
            "instance_id": instance_id,
            "message": message,
        })

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        if not self._public_login_gate(parsed, method="PATCH"):
            return
        if self._proxy_service_write(parsed, method="PATCH"):
            return
        self.send_error(404)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if not self._public_login_gate(parsed, method="PUT"):
            return
        if parsed.path == "/api/federation/config":
            self._update_federation_config()
            return
        if self._serve_manager_application(parsed, method="PUT"):
            return
        if self._proxy_service_write(parsed, method="PUT"):
            return
        self.send_error(404)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if not self._public_login_gate(parsed, method="DELETE"):
            return
        if self._proxy_job_request(parsed, method="DELETE"):
            return
        if self._serve_manager_application(parsed, method="DELETE"):
            return
        if self._proxy_service_write(parsed, method="DELETE"):
            return
        self.send_error(404)

    def _json_body(self, maximum: int) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > maximum:
            raise ValueError("request body is invalid")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def _login(self) -> None:
        if self.state.require_device_auth and not self._is_loopback_client():
            json_response(self, {
                "success": False,
                "error": "device authentication required",
            }, 403)
            return
        if not self._has_secure_ui_transport():
            json_response(self, {
                "success": False,
                "error": "login requires HTTPS outside private LAN",
            }, 400)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 16 * 1024:
            json_response(self, {
                "success": False,
                "error": "invalid login request",
            }, 400)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            token, principal, role = self.state.login(
                str(payload.get("username") or ""),
                str(payload.get("password") or ""),
            )
        except (ValueError, TypeError, json.JSONDecodeError):
            json_response(self, {
                "success": False,
                "error": "invalid login request",
            }, 400)
            return
        except PermissionError as exc:
            json_response(self, {
                "success": False,
                "error": str(exc),
            }, 403)
            return
        except Exception as exc:
            sys.stderr.write(f"[manager] login failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "manager login failed",
            }, 500)
            return
        json_response(self, {
            "success": True,
            "username": principal,
            "role": role,
            "capabilities": {
                "manager": role == "super_admin",
                "research": True,
            },
            "token": token,
            "expires_in": MANAGER_SESSION_TTL_SECONDS,
        }, headers={"Set-Cookie": self._session_cookie(token)})

    def _session_cookie(self, token: str, *, clear: bool = False) -> str:
        secure = " Secure;" if self._is_secure_transport() else ""
        if clear:
            return (
                "ft-manager-session=; Max-Age=0; HttpOnly; SameSite=Lax;"
                f"{secure} Path=/"
            )
        return (
            f"ft-manager-session={token}; "
            f"Max-Age={MANAGER_SESSION_TTL_SECONDS}; "
            f"HttpOnly; SameSite=Lax;{secure} Path=/"
        )

    def _register(self) -> None:
        if self.state.require_device_auth and not self._is_loopback_client():
            json_response(self, {
                "success": False,
                "error": PUBLIC_DEVICE_COMPLIANCE_NOTICE,
                "code": "public_device_auth_required",
            }, 403)
            return
        if not self.state.public_registration_enabled:
            json_response(self, {
                "success": False,
                "error": PUBLIC_REGISTRATION_NOTICE,
                "code": "public_registration_disabled",
            }, 403)
            return
        if not self._has_secure_ui_transport():
            json_response(self, {"success": False, "error": "registration requires HTTPS outside private LAN"}, 400)
            return
        try:
            payload = self._json_body(16 * 1024)
            principal, role, alias, organization_id = self.state.register(
                str(payload.get("username") or payload.get("alias") or ""),
                str(payload.get("password") or ""),
                str(payload.get("organization_id") or ""),
            )
            token = self.state.login(principal, str(payload.get("password") or ""))[0]
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return
        json_response(
            self,
            {"success": True, "token": token, "username": principal, "alias": alias, "role": role, "organization_id": organization_id, "capabilities": {"manager": role == "super_admin", "research": True}},
            headers={"Set-Cookie": self._session_cookie(token)},
        )

    def _resolve_operation(self, instance_id: str):
        if self.path == "/vibe/start":
            if instance_id != "service-vibe-trading":
                raise LookupError("managed instance not found")
            return self.state.start_vibe
        if self.path == "/vibe/stop":
            if instance_id != "service-vibe-trading":
                raise LookupError("managed instance not found")
            return self.state.stop_vibe
        worktree = self.state.worktree_for_instance(instance_id)
        if worktree is None:
            raise LookupError("managed instance not found")
        if self.path == "/start":
            return lambda: self.state.start(worktree.path, worktree.port)
        if self.path == "/stop":
            return lambda: self.state.stop(worktree.path)
        if self.path == "/restart-api":
            return lambda: self.state.restart_api(worktree.path, worktree.port)
        if self.path == "/restart-bundle":
            return lambda: self.state.restart_bundle(worktree.path, worktree.port)
        return lambda: self.state.stop(worktree.path, force=True)

    def _serve_client_release(self, path: str) -> bool:
        public_key = (
            Path(__file__).resolve().parents[2]
            / "tools/cli/release/trusted-beta-release-public.pem"
        )
        try:
            if path == "/api/client/releases/beta.json":
                raw, etag = load_client_release_channel(
                    self.state.release_root, "beta", public_key=public_key,
                )
                self._release_bytes(raw, "application/json", etag)
                return True
            if path == "/api/client/releases/beta.xml":
                raw, etag = load_beta_sparkle_appcast(
                    self.state.release_root, public_key=public_key,
                )
                self._release_bytes(raw, "application/rss+xml", etag)
                return True
            match = re.fullmatch(
                r"/api/client/releases/assets/beta/([0-9a-f]{64})\.(dmg|delta)",
                path,
            )
            if match:
                self._release_asset(match.group(1), match.group(2))
                return True
        except FileNotFoundError:
            json_response(self, {"success": False, "error": "release not found"}, 404)
            return True
        except (OSError, ValueError):
            json_response(self, {"success": False, "error": "release unavailable"}, 503)
            return True
        return False

    def _release_bytes(self, raw: bytes, content_type: str, etag: str) -> None:
        if self.headers.get("If-None-Match", "").strip('"') == etag:
            self.send_response(304)
            self.send_header("ETag", f'"{etag}"')
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("ETag", f'"{etag}"')
        self.send_header("Cache-Control", "public, max-age=60")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def _release_asset(self, digest: str, suffix: str) -> None:
        asset = self.state.release_root / "assets/beta" / f"{digest}.{suffix}"
        resolved = asset.resolve(strict=True)
        expected_parent = (self.state.release_root / "assets/beta").resolve()
        if resolved.parent != expected_parent or not resolved.is_file():
            raise FileNotFoundError(asset)
        hasher = hashlib.sha256()
        with resolved.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                hasher.update(chunk)
        if hasher.hexdigest() != digest:
            raise ValueError("release asset digest mismatch")
        size = resolved.stat().st_size
        start, end, status = 0, size - 1, 200
        header = self.headers.get("Range", "")
        if header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
            if not match or (not match.group(1) and not match.group(2)):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2) or end)
            else:
                length = int(match.group(2))
                start = max(0, size - length)
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            end = min(end, size - 1)
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("ETag", f'"{digest}"')
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with resolved.open("rb") as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("[manager] " + (fmt % args) + "\n")


def main(argv=None) -> int:
    """Compatibility call for callers that still import the old module.

    The process bootstrap lives in :mod:`server.manager.app`.  Passing this
    module into the app keeps the historical test and extension seam working
    while the HTTP implementation is split into its server package.
    """
    from server.manager.app import main as app_main

    return app_main(argv=argv, runtime_module=sys.modules[__name__])
