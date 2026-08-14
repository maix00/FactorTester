#!/usr/bin/env python3
"""FactorTester Manager runtime state and HTTP route composition.

Process configuration and listener lifecycle live in ``server.manager.app``.
This module composes the Manager state and canonical HTTP route modules.
"""

from __future__ import annotations

import ipaddress
import inspect
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from server.manager.config import (
    MANAGER_SESSION_REFRESH_WINDOW_SECONDS,
    MANAGER_SESSION_TTL_SECONDS,
)
from server.manager.http.gateway import GatewayResponse, ServiceGateway
from server.manager.http.device_routes import DeviceNetworkRoutesMixin
from server.manager.http.control_database_routes import ControlDatabaseRoutesMixin
from server.manager.http.request_security import RequestSecurityMixin
from server.manager.http.federation_routes import FederationRoutesMixin
from server.manager.http.catalog_routes import CatalogRoutesMixin
from server.manager.http.service_selection import ServiceSelectionRoutesMixin
from server.manager.http.job_proxy_routes import JobProxyRoutesMixin
from server.manager.http.job_transfer_routes import JobTransferRoutesMixin
from server.manager.http.core_get_routes import CoreGetRoutesMixin
from server.manager.http.job_list_routes import JobListRoutesMixin
from server.manager.http.client_research_routes import ClientResearchRoutesMixin
from server.manager.http.public_research_routes import PublicResearchRoutesMixin
from server.manager.http.write_routes import WriteRoutesMixin
from server.manager.http.auth_routes import AuthenticationRoutesMixin
from server.manager.http.client_release_routes import ClientReleaseRoutesMixin
from server.manager.services.client_state import ClientStateService
from server.manager.services.federated_public_data import (
    FederatedPublicDataService,
)
from server.manager.domain.accounts import (
    account_role as _account_role,
    authenticate_user as _authenticate_user,
    manager_subordinate_users as _manager_subordinate_users,
)
from server.manager.domain.organization_scope import configured_managed_organizations
from server.manager.storage.preferences import UserPreferenceStore
from server.manager.storage.job_index import ManagerJobIndex
from server.manager.storage.sqlite import ManagerSQLiteWeb, ManagerSQLiteResponse
from server.manager.domain.federation import (
    FederatedGateway,
    FederationNodeDirectory,
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
from server.manager.storage.control_database_settings import (
    ControlDatabaseSettingsStore,
)
from server.manager.storage.service_intents import ServiceIntentStore
from server.manager.http.security import (
    configured_trusted_proxy_networks,
    configured_tls_paths,
    enable_server_tls,
    server_tls_context,
)
from server.manager.http.visitor_access import (
    VisitorAccessStore,
    configured_manager_endpoint,
    configured_visitor_origins,
)
from server.manager.state.models import (
    ServiceBundle,
    Worktree,
)
from server.manager.state.sessions import SessionStateMixin
from server.manager.state.control_database import ControlDatabaseStateMixin
from server.manager.state.federation_membership import (
    FederationMembershipStateMixin,
)
from server.manager.state.federation_settings import FederationSettingsStateMixin
from server.manager.state.routing import RoutingStateMixin
from server.manager.state.jobs import JobProjectionStateMixin
from server.manager.state.worktrees import WorktreeStateMixin
from server.manager.state.processes import ProcessStateMixin
from server.manager.state.data_plane_process import DataPlaneProcessStateMixin
from server.manager.state.transfer_access import TransferAccessStateMixin
from server.manager.state.transfers import TransferStateMixin
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
    ControlDatabaseStateMixin,
    FederationMembershipStateMixin,
    FederationSettingsStateMixin,
    RoutingStateMixin,
    JobProjectionStateMixin,
    WorktreeStateMixin,
    ProcessStateMixin,
    DataPlaneProcessStateMixin,
    TransferAccessStateMixin,
    TransferStateMixin,
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
        managed_organizations: tuple[str, ...] | None = None,
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
        self.managed_organizations = configured_managed_organizations(
            public_server=self.public_server,
            server_role=self.server_role,
            explicit=managed_organizations,
        )
        self.trusted_proxy_networks = configured_trusted_proxy_networks()
        self.visitor_entry_origins = configured_visitor_origins()
        self.manager_public_endpoint = configured_manager_endpoint()
        self.visitor_access = VisitorAccessStore()
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
        self.service_intents = ServiceIntentStore(
            self.state_root / "desired-services.json",
        )
        self.capability_path = self.state_root / "manager-capability.key"
        self.federation_proxy_path = self.state_root / "federation-proxy.key"
        self.release_root = self.state_root / "client-releases"
        self._init_transfer_state()
        self._init_transfer_access()
        self._init_data_plane_process()
        self.sessions_path = self.state_root / "sessions.json"
        # Account, organisation, hierarchy, profile, quota, and device
        # identity records share one PostgreSQL control plane when deployed.
        # The constructor is lazy: an unavailable database is reported by the
        # relevant request instead of preventing a local Manager from starting.
        self.control_database_settings = ControlDatabaseSettingsStore(
            self.state_root / "control-database.json",
        )
        control_database_environ = (
            self.control_database_settings.effective_environ()
        )
        self.control_store = control_store_from_env(control_database_environ)
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
        self.federation_directory = FederationNodeDirectory()
        self.federation_sync = FederationSyncWorker(
            server_id=self.server_id,
            job_index=self.job_index,
            gateway=self.federation_gateway,
            peer_provider=lambda: self.federation_registry.servers(
                include_offline=True,
            ),
            local_refresh=self.refresh_local_job_projection,
        )
        self._capability_cache: dict[
            tuple[str, int, str], tuple[float, dict[str, object]]
        ] = {}
        self._capability_cache_lock = threading.RLock()
        self._sessions = self._load_sessions()
        self._session_lock = threading.Lock()
        self.public_research = PublicResearchLibrary(
            self.data_root / "public-research",
        )
        self.client_state = ClientStateService(control_store=self.control_store)
        self.federated_public_data = FederatedPublicDataService(
            server_id=self.server_id,
            registry=self.federation_registry,
            gateway=self.federation_gateway,
            public_research=self.public_research,
            client_state=self.client_state,
        )
        # Keep the route name explicit: public research is a read-through
        # projection, while ``public_research`` remains the local authority
        # used by publication writes.
        self.federated_public_research = self.federated_public_data
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
            control_store=self.control_store,
        )
        self.gateway = ServiceGateway(
            available_ports=self.service_ports,
            capability_token=self.capability_token,
        )
        self.sqlite_web = ManagerSQLiteWeb(self)

    def _authenticate_credentials(
        self,
        username: str,
        password: str,
        *,
        control_store: object | None = None,
    ) -> tuple[str, str]:
        """Invoke the composition-root authentication seam."""
        kwargs = {}
        try:
            if "managed_organizations" in inspect.signature(
                _authenticate_user
            ).parameters:
                kwargs["managed_organizations"] = self.managed_organizations
        except (TypeError, ValueError):
            # Keep the small two-argument seam usable for injected test and
            # compatibility authenticators.
            pass
        if control_store is None:
            return _authenticate_user(username, password, **kwargs)
        return _authenticate_user(
            username,
            password,
            control_store=control_store,
            **kwargs,
        )

    @staticmethod
    def _role_for_account(account: dict[str, object]) -> str:
        return _account_role(account)

    @staticmethod
    def _port_is_in_use(port: int) -> bool:
        """Centralize the port-availability seam used by Manager state."""
        return port_in_use(port)

class Handler(
    RequestSecurityMixin,
    DeviceNetworkRoutesMixin,
    ControlDatabaseRoutesMixin,
    FederationRoutesMixin,
    CatalogRoutesMixin,
    ServiceSelectionRoutesMixin,
    JobProxyRoutesMixin,
    JobTransferRoutesMixin,
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

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("[manager] " + (fmt % args) + "\n")
