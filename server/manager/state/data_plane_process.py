"""Lifecycle and explicit endpoint configuration for the transfer data plane."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from scripts.data_dir import CACHE_DB_PATH

from server.manager.config import CLIENT_DATA_PORT, PEER_CONTROL_PORT, PEER_DATA_PORT
from server.manager.http.security import configured_tls_paths
from server.manager.network_endpoints import (
    peer_bind_address,
    server_endpoints,
    validate_client_endpoint,
)
from server.manager.services.network_info import local_internal_addresses
from server.manager.storage.control_db import CONTROL_DATABASE_ENV


@dataclass(frozen=True, slots=True)
class DataPlaneProcessConfig:
    client_host: str
    client_port: int
    client_control_endpoint: str
    client_data_endpoint: str
    overlay_bind_address: str = ""
    peer_port: int = PEER_DATA_PORT

    @property
    def peer_host(self) -> str:
        """Compatibility alias for callers predating the overlay terminology."""
        return self.overlay_bind_address


def _port(value: object, *, name: str) -> int:
    try:
        selected = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not 1 <= selected <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535")
    return selected


class DataPlaneProcessStateMixin:
    """Own the one child process serving public 7997 and peer 17997."""

    def _init_data_plane_process(self) -> None:
        self.data_plane_process: subprocess.Popen | None = None
        self.data_plane_process_config: DataPlaneProcessConfig | None = None
        self.transfer_submission_root = (self.data_root / "submissions").resolve()

    def configure_data_plane(
        self,
        *,
        client_host: str,
        client_port: int = CLIENT_DATA_PORT,
        client_control_endpoint: str,
        client_data_endpoint: str,
        overlay_bind_address: str = "",
        peer_host: str | None = None,
        peer_port: int = PEER_DATA_PORT,
        peer_control_port: int = PEER_CONTROL_PORT,
    ) -> DataPlaneProcessConfig:
        public_host = str(client_host or "").strip()
        if not public_host:
            raise ValueError("client data listener host is required")
        selected_client_port = _port(client_port, name="client data port")
        selected_peer_port = _port(peer_port, name="peer data port")
        control_endpoint = validate_client_endpoint(
            client_control_endpoint,
            name="client control endpoint",
        )
        data_endpoint = validate_client_endpoint(
            client_data_endpoint,
            name="client data endpoint",
        )
        legacy_address = str(peer_host or "").strip()
        selected_overlay_address = str(overlay_bind_address or "").strip()
        if (
            legacy_address
            and selected_overlay_address
            and legacy_address != selected_overlay_address
        ):
            raise ValueError("overlay bind address conflicts with legacy peer host")
        selected_overlay_address = (
            selected_overlay_address or legacy_address
        )
        if selected_overlay_address:
            selected_overlay_address = peer_bind_address(
                selected_overlay_address,
            )
            endpoints = server_endpoints(
                client_control_endpoint=control_endpoint,
                client_data_endpoint=data_endpoint,
                overlay_bind_address=selected_overlay_address,
                peer_control_port=_port(
                    peer_control_port,
                    name="peer control port",
                ),
                peer_data_port=selected_peer_port,
            )
            self.configure_transfer_endpoints(endpoints)
        self.data_plane_process_config = DataPlaneProcessConfig(
            client_host=public_host,
            client_port=selected_client_port,
            client_control_endpoint=control_endpoint,
            client_data_endpoint=data_endpoint,
            overlay_bind_address=selected_overlay_address,
            peer_port=selected_peer_port,
        )
        self.configure_transfer_access(data_endpoint)
        return self.data_plane_process_config

    def start_data_plane(self) -> str:
        config = self.data_plane_process_config
        if config is None:
            raise RuntimeError("transfer data plane is not configured")
        process = self.data_plane_process
        if process is not None and process.poll() is None:
            return f"transfer data plane already running (pid {process.pid})"
        if self._port_is_in_use(config.client_port):
            return f"transfer data port {config.client_port} already in use"

        log_file = self.log_dir / f"transfer-data-{config.client_port}.log"
        log = log_file.open("ab", buffering=0)
        environment = os.environ.copy()
        # User/account/quota PostgreSQL is deliberately outside the byte path.
        environment.pop(CONTROL_DATABASE_ENV, None)
        command = [
            self.python,
            "-m",
            "server.manager.data_plane.app",
            "--server-id",
            self.server_id,
            "--client-host",
            config.client_host,
            "--client-port",
            str(config.client_port),
            "--transfer-database",
            str(self.transfer_database_path),
            "--node-key",
            str(self.node_identity_path),
            "--job-database",
            str(Path(CACHE_DB_PATH).expanduser().resolve()),
            "--artifact-root",
            str((self.data_root / "job-results").resolve()),
            "--submission-root",
            str((self.data_root / "submissions").resolve()),
            "--research-catalog-database",
            str(Path(CACHE_DB_PATH).expanduser().resolve()),
            "--research-root",
            str((self.data_root / "public-research").resolve()),
            "--factor-source-database",
            str(Path(CACHE_DB_PATH).expanduser().resolve()),
            "--local-run-database",
            str((self.state_root / "local-run-projection.sqlite").resolve()),
            "--profile-workspace-root",
            str(self.data_root.resolve()),
            "--origin-cache-root",
            str((self.data_root / "object-cache").resolve()),
            "--release-root",
            str(self.release_root.resolve()),
            "--release-trust-root",
            str(
                (self.runtime_source_root /
                 "tools/cli/release/trusted-beta-release-public.pem").resolve()
            ),
            "--release-origin",
            str(config.client_control_endpoint),
        ]
        for origin in _client_origins(
            config.client_control_endpoint,
            public_server=bool(getattr(self, "public_server", False)),
        ):
            command.extend(["--allowed-origin", origin])
        if config.overlay_bind_address:
            command.extend([
                "--overlay-bind-address",
                config.overlay_bind_address,
                "--peer-port",
                str(config.peer_port),
            ])
        tls_paths = configured_tls_paths(
            os.environ.get("FACTORTESTER_ARTIFACT_TLS_CERT")
            or os.environ.get("FACTORTESTER_MANAGER_TLS_CERT"),
            os.environ.get("FACTORTESTER_ARTIFACT_TLS_KEY")
            or os.environ.get("FACTORTESTER_MANAGER_TLS_KEY"),
            certificate_env="FACTORTESTER_ARTIFACT_TLS_CERT",
            private_key_env="FACTORTESTER_ARTIFACT_TLS_KEY",
        )
        if tls_paths is not None:
            command.extend([
                "--tls-cert",
                str(tls_paths[0]),
                "--tls-key",
                str(tls_paths[1]),
            ])
        self.data_plane_process = subprocess.Popen(
            command,
            cwd=self.repo,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        peer = (
            f" and {config.overlay_bind_address}:{config.peer_port}"
            if config.overlay_bind_address
            else ""
        )
        return (
            f"started transfer data pid {self.data_plane_process.pid} on "
            f"{config.client_host}:{config.client_port}{peer}"
        )

    def stop_data_plane(self) -> None:
        process = self.data_plane_process
        self.data_plane_process = None
        if process is not None:
            self._terminate(process)


__all__ = ["DataPlaneProcessConfig", "DataPlaneProcessStateMixin"]


def _origin(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    return f"{parsed.scheme}://{parsed.netloc}"


def _client_origins(endpoint: str, *, public_server: bool) -> tuple[str, ...]:
    """Return browser origins allowed to use this Manager's 7997 endpoint.

    The capability URL is intentionally a client-facing endpoint, while the
    data process also listens on the server's WireGuard address for peer
    traffic.  Local Docker clients may open 7998 as ``127.0.0.1`` or
    ``localhost`` while the configured 7997 URL uses the host LAN address;
    those are legitimate same-machine origins and need explicit CORS
    permission.  Public deployments keep the allow-list to their configured
    public Manager origin.
    """
    primary = _origin(endpoint)
    origins = [primary]
    if public_server:
        return tuple(origins)
    parsed = urlsplit(endpoint)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    hosts = {"127.0.0.1", "localhost", "[::1]"}
    hosts.update(local_internal_addresses())
    for host in sorted(hosts):
        rendered = host
        if ":" in host and not host.startswith("["):
            rendered = f"[{host}]"
        candidate = f"{parsed.scheme}://{rendered}:{port}"
        if candidate not in origins:
            origins.append(candidate)
    return tuple(origins)
