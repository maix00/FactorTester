#!/usr/bin/env python3
"""FactorTester Manager runtime: state, services, and HTTP route dispatch.

Process configuration and listener lifecycle are intentionally kept in
``server.manager.app``.  This module is the implementation behind that
minimal bootstrap and remains import-compatible with the former
``scripts.worktree_flask_manager`` path during the server-package migration.
"""

from __future__ import annotations

import html
import ipaddress
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser  # compatibility export for the former script module
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from server.manager.config import (
    MANAGER_SESSION_REFRESH_WINDOW_SECONDS,
    MANAGER_SESSION_TTL_SECONDS,
    VIBE_TRADING_PORT,
)
from server.manager.http.gateway import GatewayResponse, ServiceGateway
from server.manager.http.device_routes import DeviceNetworkRoutesMixin
from server.manager.http.request_security import RequestSecurityMixin
from server.manager.http.federation_routes import FederationRoutesMixin
from server.manager.http.catalog_routes import CatalogRoutesMixin
from server.manager.http.service_selection import (
    ServiceSelectionRoutesMixin,
    _SERVICE_GET_PREFIXES,
)
from server.manager.http.job_proxy_routes import (
    JobProxyRoutesMixin,
    _SERVICE_WRITE_PATTERNS,
)
from server.manager.http.core_get_routes import CoreGetRoutesMixin
from server.manager.http.job_list_routes import JobListRoutesMixin
from server.manager.http.client_research_routes import ClientResearchRoutesMixin
from server.manager.http.public_research_routes import PublicResearchRoutesMixin
from server.manager.http.write_routes import WriteRoutesMixin
from server.manager.http.auth_routes import AuthenticationRoutesMixin
from server.manager.http.client_release_routes import ClientReleaseRoutesMixin
from server.manager.services.client_state import ClientStateService
from server.manager.domain.accounts import (
    account_role as _account_role,
    authenticate_user as _authenticate_user,
    manager_subordinate_users as _manager_subordinate_users,
)
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
)
from server.manager.services.test_authoring import TestAuthoringService
from server.manager.http.pages import (
    PUBLIC_DEVICE_COMPLIANCE_NOTICE,
    PUBLIC_REGISTRATION_NOTICE,
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
    ServiceBundle,
    Worktree,
)
from server.manager.state.sessions import SessionStateMixin
from server.manager.state.routing import RoutingStateMixin
from server.manager.state.jobs import JobProjectionStateMixin
from server.manager.state.worktrees import WorktreeStateMixin
from server.manager.state.processes import ProcessStateMixin
from server.manager.system import (
    lan_ip as _lan_ip,
    port_in_use,
)
from tools.cli.release.research_reporting.public_research import (
    PublicResearchLibrary,
)


VIBE_TRADING_ROOT = Path(
    os.environ.get(
        "VIBE_TRADING_ROOT",
        "/Users/maxdeux/Documents/Vibe-Trading-Integration",
    )
).expanduser()

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


class Handler(
    RequestSecurityMixin,
    DeviceNetworkRoutesMixin,
    FederationRoutesMixin,
    CatalogRoutesMixin,
    ServiceSelectionRoutesMixin,
    JobProxyRoutesMixin,
    JobListRoutesMixin,
    ClientResearchRoutesMixin,
    PublicResearchRoutesMixin,
    WriteRoutesMixin,
    AuthenticationRoutesMixin,
    ClientReleaseRoutesMixin,
    CoreGetRoutesMixin,
    BaseHTTPRequestHandler,
):
    state: ManagerState

    @staticmethod
    def _runtime_port_in_use(port: int) -> bool:
        return port_in_use(port)

    @staticmethod
    def _runtime_lan_ip() -> str:
        return _lan_ip()

    @staticmethod
    def _subordinate_users(owner: str) -> list[dict[str, str]]:
        return _manager_subordinate_users(owner)

    def _legacy_manager_page(self, message: str) -> bytes:
        return page(self.state, message)






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
