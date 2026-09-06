#!/usr/bin/env python3
"""Minimal FactorTester Manager process bootstrap.

The Manager's state and HTTP routes live in :mod:`server.manager.runtime`.
This module owns only command-line configuration, listener lifecycle, TLS,
and shutdown.  It is the production entry point used by systemd and by
``python -m server.manager.app``.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import webbrowser
from pathlib import Path
from types import ModuleType
from typing import Sequence

from server.manager.config import (
    CLIENT_DATA_PORT,
    PEER_CONTROL_PORT,
    PEER_DATA_PORT,
)
from server.manager.http.peer_handler import peer_control_handler
from server.manager.network_endpoints import (
    client_endpoint_for_port,
    peer_bind_address,
    validate_client_endpoint,
)
from server.manager.http.visitor_access import configured_manager_endpoint


def _runtime_module() -> ModuleType:
    from server.manager import runtime

    return runtime


def _raise_keyboard_interrupt(_signum: int, _frame: object) -> None:
    """Route service-manager SIGTERM through the normal cleanup path."""
    raise KeyboardInterrupt


def build_parser(runtime_module: ModuleType | None = None) -> argparse.ArgumentParser:
    runtime_module = runtime_module or _runtime_module()
    parser = argparse.ArgumentParser(description="Run the FactorTester Manager")
    parser.add_argument(
        "--repo",
        default=str(Path(runtime_module.__file__).resolve().parents[2]),
        help="FactorTester repository root",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7998)
    parser.add_argument(
        "--overlay-bind-address",
        "--peer-host",
        dest="overlay_bind_address",
        default="",
        help=(
            "this node's FactorTester WireGuard address; required to enable "
            "peer control (--peer-host is a compatibility alias)"
        ),
    )
    parser.add_argument("--peer-port", type=int, default=PEER_CONTROL_PORT)
    parser.add_argument("--data-host", default="0.0.0.0")
    parser.add_argument("--data-port", type=int, default=CLIENT_DATA_PORT)
    parser.add_argument("--peer-data-port", type=int, default=PEER_DATA_PORT)
    parser.add_argument(
        "--public-endpoint",
        default="",
        help="Client-visible Manager endpoint; never inferred for peers",
    )
    parser.add_argument(
        "--public-data-endpoint",
        default="",
        help="Client-visible transfer data endpoint",
    )
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument(
        "--data-root",
        default="",
        help="Persistent FactorTester data root (defaults to ../FactorTester)",
    )
    parser.add_argument(
        "--server-role", choices=("main", "feat"), default=None,
        help="Control-plane role; feature Managers may attach to a main Manager",
    )
    parser.add_argument("--server-id", default=None)
    parser.add_argument("--fixed-port", type=int, default=None)
    parser.add_argument("--fixed-branch", default=None)
    parser.add_argument("--daemon-socket", default="")
    parser.add_argument("--feature", action="append", default=[])
    parser.add_argument("--state-root", default="")
    parser.add_argument(
        "--tls-cert",
        default=None,
        help="TLS certificate for direct HTTPS on the Manager port",
    )
    parser.add_argument(
        "--tls-key",
        default=None,
        help="TLS private key for direct HTTPS on the Manager port",
    )
    parser.add_argument("--no-browser", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runtime_module: ModuleType | None = None,
) -> int:
    """Start the Manager and its client/peer transfer data plane.

    ``runtime_module`` is an internal compatibility seam for the old import
    path and tests.  Production callers should simply invoke ``main()``.
    """
    runtime_module = runtime_module or _runtime_module()
    args = build_parser(runtime_module).parse_args(argv)
    if args.server_id:
        # Manager-owned source hydration and catalog writes use the same
        # provider identity as its execution-service subprocesses.
        os.environ['FACTORTESTER_SERVER_ID'] = str(args.server_id).strip()
    tls_paths = runtime_module.configured_tls_paths(
        args.tls_cert,
        args.tls_key,
        certificate_env="FACTORTESTER_MANAGER_TLS_CERT",
        private_key_env="FACTORTESTER_MANAGER_TLS_KEY",
    )

    runtime_module.Handler.state = runtime_module.ManagerState(
        Path(args.repo), args.python,
        Path(args.data_root) if args.data_root else None,
        server_role=args.server_role,
        server_id=args.server_id,
        fixed_port=args.fixed_port,
        fixed_branch=args.fixed_branch,
        features=tuple(args.feature),
        state_root=Path(args.state_root) if args.state_root else None,
        fixed_daemon_socket=args.daemon_socket or None,
        session_db_path=runtime_module.configured_manager_sqlite_path(),
    )
    removed = runtime_module.Handler.state.cleanup_detached_worktrees()
    if removed:
        print(f"Removed {len(removed)} detached worktree(s)")

    scheme = "https" if tls_paths is not None else "http"
    control_endpoint = str(
        args.public_endpoint
        or os.environ.get("FACTORTESTER_MANAGER_PUBLIC_ENDPOINT")
        or ""
    ).strip().rstrip("/")
    if not control_endpoint:
        control_endpoint = f"{scheme}://127.0.0.1:{args.port}"
    control_endpoint = validate_client_endpoint(
        control_endpoint, name="public Manager endpoint",
    )
    runtime_module.Handler.state.manager_public_endpoint = (
        configured_manager_endpoint(control_endpoint)
    )
    if not runtime_module.Handler.state.agent_manager_endpoint:
        runtime_module.Handler.state.agent_manager_endpoint = (
            f"http://127.0.0.1:{args.port}"
        )
    data_endpoint = str(
        args.public_data_endpoint
        or os.environ.get("FACTORTESTER_ARTIFACT_PUBLIC_ENDPOINT")
        or ""
    ).strip().rstrip("/")
    if not data_endpoint:
        data_endpoint = client_endpoint_for_port(
            control_endpoint,
            args.data_port,
            name="public transfer data endpoint",
        )
    else:
        data_endpoint = validate_client_endpoint(
            data_endpoint, name="public transfer data endpoint",
        )
    runtime_module.Handler.state.configure_data_plane(
        client_host=args.data_host,
        client_port=args.data_port,
        client_control_endpoint=control_endpoint,
        client_data_endpoint=data_endpoint,
        overlay_bind_address=args.overlay_bind_address,
        peer_port=args.peer_data_port,
        peer_control_port=args.peer_port,
    )

    # The control plane is bound before 7997.  Other worktree services (8000
    # and feature ports) remain explicitly managed by the control plane.
    server = runtime_module.ThreadingHTTPServer(
        (args.host, args.port), runtime_module.Handler,
    )
    tls_context = None
    if tls_paths is not None:
        tls_context = runtime_module.server_tls_context(*tls_paths)
        runtime_module.enable_server_tls(
            server,
            tls_context,
            allow_plain_http=True,
        )

    previous_sigterm_handler: object | None = None
    sigterm_handler_installed = False
    try:
        previous_sigterm_handler = signal.signal(
            signal.SIGTERM, _raise_keyboard_interrupt,
        )
        sigterm_handler_installed = True
    except ValueError:
        # Tests and embedders may run the Manager outside the main thread.
        pass

    ipv6_server = None
    peer_server = None
    try:
        try:
            if args.overlay_bind_address:
                overlay_bind_address = peer_bind_address(
                    args.overlay_bind_address,
                )
                peer_server = runtime_module.ThreadingHTTPServer(
                    (overlay_bind_address, args.peer_port),
                    peer_control_handler(runtime_module.Handler.state),
                )
                threading.Thread(
                    target=peer_server.serve_forever,
                    name="manager-peer-control",
                    daemon=True,
                ).start()
                print(
                    "  Peer control: "
                    f"http://{overlay_bind_address}:{args.peer_port}/"
                )
            if args.host in {"0.0.0.0", "127.0.0.1", "localhost"}:
                try:
                    ipv6_server = runtime_module.IPv6LoopbackHTTPServer(
                        ("::1", args.port), runtime_module.Handler,
                    )
                    if tls_context is not None:
                        runtime_module.enable_server_tls(
                            ipv6_server,
                            tls_context,
                            allow_plain_http=True,
                        )
                    ipv6_thread = threading.Thread(
                        target=ipv6_server.serve_forever,
                        name="manager-ipv6-loopback",
                        daemon=True,
                    )
                    ipv6_thread.start()
                    scheme = "https" if tls_context is not None else "http"
                    print(f"  IPv6 loopback: {scheme}://[::1]:{args.port}/")
                except OSError as exc:
                    # IPv4 remains usable on systems where IPv6 is disabled.
                    print(f"  IPv6 loopback unavailable: {exc}")

            print(runtime_module.Handler.state.start_data_plane())
            for restored in runtime_module.Handler.state.restore_desired_services():
                status = str(restored.get("status") or "")
                message = (
                    "Manager service intent "
                    f"{status}: {restored.get('path')}:{restored.get('port')}"
                )
                if status == "error":
                    print(
                        f"{message} ({restored.get('error')})",
                        file=sys.stderr,
                    )
                else:
                    print(message)
            runtime_module.Handler.state.start_configured_federation()
            scheme = "https" if tls_context is not None else "http"
            url = f"{scheme}://localhost:{args.port}/"
            print(f"Worktree Flask manager running at {url}")
            try:
                for lan_ip in runtime_module.Handler.state.local_internal_addresses():
                    print(f"  局域网访问: {scheme}://{lan_ip}:{args.port}/")
            except Exception:
                # Address display is advisory and must not stop the listener.
                pass
            if not args.no_browser:
                webbrowser.open(url)
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    finally:
        if peer_server is not None:
            peer_server.shutdown()
            peer_server.server_close()
        if ipv6_server is not None:
            ipv6_server.shutdown()
            ipv6_server.server_close()
        try:
            runtime_module.Handler.state.stop_all()
        finally:
            server.server_close()
            if sigterm_handler_installed:
                signal.signal(signal.SIGTERM, previous_sigterm_handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
