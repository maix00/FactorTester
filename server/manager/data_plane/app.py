#!/usr/bin/env python3
"""Minimal production entry point for public and WireGuard transfer bytes."""

from __future__ import annotations

import argparse
import signal
import threading
from collections.abc import Sequence
from pathlib import Path

from server.manager.config import CLIENT_DATA_PORT, PEER_DATA_PORT
from server.manager.data_plane.artifacts import ArtifactOriginResolver
from server.manager.data_plane.context import DataPlaneRuntime
from server.manager.data_plane.local_runs import LocalRunArtifactOriginAdapter
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
from server.manager.objects.adapters.client_release import (
    ClientReleaseDestinationAdapter,
)
from server.manager.objects.adapters.evidence_file import (
    EvidenceFileDestinationAdapter,
    EvidenceFileOriginAdapter,
)
from server.manager.objects.adapters.factor_source import (
    FactorSourceDestinationAdapter,
    FactorSourceOriginAdapter,
)
from server.manager.objects.adapters.profile_workspace import (
    ProfileWorkspaceOriginAdapter,
)
from server.manager.objects.adapters.public_research import PublicResearchOriginAdapter
from server.manager.objects.adapters.public_research_destination import (
    PublicResearchDestinationAdapter,
)
from server.manager.objects.destination import ObjectDestinationRegistry
from server.manager.objects.models import TransferObjectKind
from server.manager.objects.origin import ObjectOriginRegistry
from server.manager.transfers.node_keys import NodeKey
from server.manager.transfers.peer_gateway import TransferPeerGateway
from tools.cli.release.research_reporting.public_research.library import (
    PublicResearchLibrary,
)
from tools.cli.release.research_reporting.public_research.object_store import (
    PublicResearchObjectStore,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run FactorTester transfer data")
    parser.add_argument("--server-id", required=True)
    parser.add_argument("--client-host", default="0.0.0.0")
    parser.add_argument("--client-port", type=int, default=CLIENT_DATA_PORT)
    parser.add_argument(
        "--overlay-bind-address",
        "--peer-host",
        dest="overlay_bind_address",
        default="",
        help="this node's FactorTester WireGuard address",
    )
    parser.add_argument("--peer-port", type=int, default=PEER_DATA_PORT)
    parser.add_argument("--transfer-database", required=True)
    parser.add_argument("--node-key", required=True)
    parser.add_argument("--job-database", required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--submission-root", required=True)
    parser.add_argument("--research-root", default="")
    parser.add_argument("--factor-source-database", default="")
    parser.add_argument("--local-run-database", default="")
    parser.add_argument("--profile-workspace-root", default="")
    parser.add_argument("--origin-cache-root", default="")
    parser.add_argument("--release-root", default="")
    parser.add_argument("--release-trust-root", default="")
    parser.add_argument("--release-origin", default="")
    parser.add_argument("--allowed-origin", action="append", default=[])
    parser.add_argument("--tls-cert", default=None)
    parser.add_argument("--tls-key", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    key = NodeKey.load_or_create(args.node_key, node_id=args.server_id)
    peer = TransferPeerGateway(key=key)
    artifact_resolver = ArtifactOriginResolver(
        job_database=args.job_database,
        artifact_root=args.artifact_root,
    )
    adapters = {}
    research_store = None
    if args.research_root:
        research = PublicResearchLibrary(
            Path(args.research_root), storage_server_id=args.server_id,
        )
        research_store = PublicResearchObjectStore(research)
        adapters[TransferObjectKind.RESEARCH_ASSET.value] = PublicResearchOriginAdapter(
            research_store,
        )
        adapters[TransferObjectKind.RESEARCH_ATTACHMENT.value] = PublicResearchOriginAdapter(
            research_store,
        )
        adapters[TransferObjectKind.RESEARCH_LOCAL_RESOURCE.value] = PublicResearchOriginAdapter(
            research_store,
        )
        evidence_root = Path(args.research_root) / "evidence-files"
        adapters[TransferObjectKind.EVIDENCE_FILE.value] = EvidenceFileOriginAdapter(
            evidence_root,
        )
    if args.factor_source_database:
        adapters[TransferObjectKind.FACTOR_SOURCE.value] = FactorSourceOriginAdapter(
            database=args.factor_source_database,
            cache_root=args.origin_cache_root or args.submission_root,
        )
    if args.local_run_database:
        adapters[TransferObjectKind.LOCAL_RUN_ARTIFACT.value] = LocalRunArtifactOriginAdapter(
            database=args.local_run_database,
            submission_root=args.submission_root,
        )
    if args.profile_workspace_root:
        adapters[TransferObjectKind.PROFILE_WORKSPACE.value] = ProfileWorkspaceOriginAdapter(
            data_root=args.profile_workspace_root,
        )
    destination_adapters = {}
    if args.release_root and args.release_trust_root:
        destination_adapters[TransferObjectKind.CLIENT_RELEASE.value] = (
            ClientReleaseDestinationAdapter(
                release_root=args.release_root,
                public_key=args.release_trust_root,
                expected_origin=args.release_origin,
            )
        )
    if research_store is not None:
        research_destination = PublicResearchDestinationAdapter(research_store)
        for kind in (
            TransferObjectKind.RESEARCH_ASSET.value,
            TransferObjectKind.RESEARCH_ATTACHMENT.value,
            TransferObjectKind.RESEARCH_LOCAL_RESOURCE.value,
        ):
            destination_adapters[kind] = research_destination
        destination_adapters[TransferObjectKind.EVIDENCE_FILE.value] = (
            EvidenceFileDestinationAdapter(Path(args.research_root) / "evidence-files")
        )
    if args.factor_source_database:
        destination_adapters[TransferObjectKind.FACTOR_SOURCE.value] = (
            FactorSourceDestinationAdapter(database=args.factor_source_database)
        )
    runtime = DataPlaneRuntime(
        server_id=args.server_id,
        transfer_database=args.transfer_database,
        staging_root=args.submission_root,
        origin_resolver=ObjectOriginRegistry(
            adapters=adapters,
            fallback=artifact_resolver,
        ),
        origin_ticket_provider=peer.origin_ticket,
        destination_ticket_provider=peer.destination_ticket,
        destination_committer=(
            ObjectDestinationRegistry(destination_adapters)
            if destination_adapters else None
        ),
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
    if args.overlay_bind_address:
        overlay_bind_address = peer_bind_address(args.overlay_bind_address)
        peer_server = PeerDataPlaneHTTPServer(
            (overlay_bind_address, args.peer_port), runtime=runtime,
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
            "FactorTester peer data listening on "
            f"{args.overlay_bind_address}:{args.peer_port}",
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
