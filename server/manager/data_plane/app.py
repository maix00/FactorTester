#!/usr/bin/env python3
"""Minimal production entry point for public and WireGuard transfer bytes."""

from __future__ import annotations

import argparse
import signal
import threading
from pathlib import Path
from typing import Sequence

from server.manager.config import ARTIFACT_DATA_PORT, PEER_DATA_PORT
from server.manager.data_plane.artifacts import ArtifactOriginResolver
from server.manager.data_plane.context import DataPlaneRuntime
from server.manager.data_plane.server import (
    ClientDataPlaneHTTPServer,
    PeerDataPlaneHTTPServer,
)
from server.manager.http.security import (
    configured_tls_paths,
    enable_server_tls,
    server_tls_context,
)
from server.manager.network_endpoints import peer_bind_address
from server.manager.transfers.node_keys import NodeKey
from server.manager.transfers.peer_gateway import TransferPeerGateway


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run FactorTester transfer data")
    parser.add_argument("--server-id", required=True)
    parser.add_argument("--client-host", default="0.0.0.0")
    parser.add_argument("--client-port", type=int, default=ARTIFACT_DATA_PORT)
    parser.add_argument("--peer-host", default="")
    parser.add_argument("--peer-port", type=int, default=PEER_DATA_PORT)
    parser.add_argument("--transfer-database", required=True)
    parser.add_argument("--node-key", required=True)
    parser.add_argument("--job-database", required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--submission-root", required=True)
    parser.add_argument("--allowed-origin", action="append", default=[])
    parser.add_argument("--tls-cert", default=None)
    parser.add_argument("--tls-key", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    key = NodeKey.load_or_create(args.node_key, node_id=args.server_id)
    peer = TransferPeerGateway(key=key)
    runtime = DataPlaneRuntime(
        server_id=args.server_id,
        transfer_database=args.transfer_database,
        staging_root=args.submission_root,
        origin_resolver=ArtifactOriginResolver(
            job_database=args.job_database,
            artifact_root=args.artifact_root,
        ),
        origin_ticket_provider=peer.origin_ticket,
        destination_ticket_provider=peer.destination_ticket,
        allowed_origins=tuple(args.allowed_origin),
    )
    client = ClientDataPlaneHTTPServer(
        (args.client_host, args.client_port), runtime=runtime,
    )
    tls_paths = configured_tls_paths(
        args.tls_cert,
        args.tls_key,
        certificate_env="FACTORTESTER_ARTIFACT_TLS_CERT",
        private_key_env="FACTORTESTER_ARTIFACT_TLS_KEY",
    )
    if tls_paths is not None:
        enable_server_tls(client, server_tls_context(*tls_paths))

    peer_server = None
    peer_thread = None
    if args.peer_host:
        peer_host = peer_bind_address(args.peer_host)
        peer_server = PeerDataPlaneHTTPServer(
            (peer_host, args.peer_port), runtime=runtime,
        )
        peer_thread = threading.Thread(
            target=peer_server.serve_forever,
            name="transfer-peer-data",
            daemon=True,
        )
        peer_thread.start()

    def stop(_signum=None, _frame=None) -> None:
        threading.Thread(target=client.shutdown, daemon=True).start()

    try:
        signal.signal(signal.SIGTERM, stop)
    except ValueError:
        pass
    print(
        f"FactorTester client data listening on {args.client_host}:{args.client_port}",
        flush=True,
    )
    if peer_server is not None:
        print(
            f"FactorTester peer data listening on {args.peer_host}:{args.peer_port}",
            flush=True,
        )
    try:
        client.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        client.server_close()
        if peer_server is not None:
            peer_server.shutdown()
            peer_server.server_close()
        if peer_thread is not None:
            peer_thread.join(timeout=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
