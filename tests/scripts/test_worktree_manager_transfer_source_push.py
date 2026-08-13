from __future__ import annotations

import hashlib
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from server.manager import runtime as manager
from server.manager.data_plane.server import DataPlaneHTTPServer, DataPlaneRuntime
from server.manager.storage.transfers import (
    TransferAttemptStore,
    TransferInboxStore,
    TransferReplicaStore,
    TransferStore,
    TransferTicketStore,
)
from server.manager.transfers.command_dispatch import TransferCommandDispatcher
from server.manager.transfers.command_executor import TransferCommandExecutor
from server.manager.transfers.coordinator import DownloadRequest, TransferCoordinator
from server.manager.transfers.node_agent import NodeAgent
from server.manager.transfers.node_keys import NodeKey
from server.manager.transfers.planner import NodeReachability
from server.manager.transfers.source_push import SourcePushExecutor
from server.manager.data_plane.integrity import IntegrityError
from server.manager.transfers.models import (
    AttemptRouteSnapshot,
    AttemptStatus,
    TransferAttemptRecord,
    TransferCommandRecord,
    TransferMode,
    TransferOperation,
    TransferRecord,
    TransferStatus,
)
from server.manager.transfers.wire import transfer_context_payload


@contextmanager
def _manager(state):
    handler = type(f"Handler_{state.server_id}", (manager.Handler,), {"state": state})
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@contextmanager
def _data_plane(runtime):
    server = DataPlaneHTTPServer(("127.0.0.1", 0), runtime=runtime)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_private_source_pushes_through_separate_connection_owner_manager(
    tmp_path,
) -> None:
    raw = (b"private-source-stream-" * 1024) + b"done"
    digest = hashlib.sha256(raw).hexdigest()
    source_file = tmp_path / "office-a.bin"
    source_file.write_bytes(raw)
    public_b1 = manager.ManagerState(
        tmp_path / "public-b1", "python", server_id="public-b1",
    )
    public_b2 = manager.ManagerState(
        tmp_path / "public-b2", "python", server_id="public-b2",
    )
    public_b1.federation_registration_token = "cluster-enroll"
    public_b2.federation_registration_token = "cluster-enroll"
    office_key = NodeKey.load_or_create(
        tmp_path / "office-a.key", node_id="office-a",
    )
    office_db = tmp_path / "office-a.sqlite"
    inbox = TransferInboxStore(office_db, server_id="office-a")

    relay_runtime = DataPlaneRuntime(
        server_id="public-b2",
        transfer_database=public_b2.transfer_database_path,
        staging_root=tmp_path / "public-b2-staging",
        origin_resolver=lambda _transfer: Path("/not-local"),
        relay_buffer_bytes=1024,
        relay_timeout=5,
    )
    with (
        _manager(public_b1) as b1_control,
        _manager(public_b2) as b2_control,
        _data_plane(relay_runtime) as b2_data,
    ):
        agent = NodeAgent(
            inbox=inbox,
            key=office_key,
            manager_endpoints=lambda: (b1_control,),
            enrollment_token="cluster-enroll",
            data_endpoint="http://office-a.invalid:7997",
            reachable_from=("office-a",),
        )
        agent.enroll()
        assert agent.poll_once(timeout=0) == []
        observed = public_b1.node_presence.require_live("office-a")
        dispatcher = TransferCommandDispatcher(
            manager_id="public-b2",
            key=public_b2.node_key,
            enrollment_token="cluster-enroll",
            local_hub=public_b2.node_control_hub,
        )
        coordinator = TransferCoordinator(
            manager_id="public-b2",
            data_endpoint=b2_data,
            control_endpoint=b2_control,
            requests=TransferStore(
                public_b2.transfer_database_path, server_id="public-b2",
            ),
            attempts=TransferAttemptStore(
                public_b2.transfer_database_path, server_id="public-b2",
            ),
            tickets=TransferTicketStore(
                public_b2.transfer_database_path, server_id="public-b2",
            ),
            command_dispatcher=dispatcher,
        )
        now = time.time()
        access = coordinator.prepare_download(
            DownloadRequest(
                idempotency_key="three-node-source-push",
                principal="alice",
                storage_server_id="office-a",
                job_id="job-private",
                artifact_name="result.bin",
                expected_size=len(raw),
                expected_sha256=digest,
                expires_at=now + 600,
            ),
            observations={
                "office-a": NodeReachability(
                    server_id="office-a",
                    data_endpoint=observed.data_endpoint,
                    control_endpoint="",
                    reachable_from=observed.reachable_from,
                    connection_owner_manager_id="public-b1",
                    connection_owner_control_endpoint=b1_control,
                    observed_at=now,
                    expires_at=now + 60,
                    online=True,
                ),
                "public-b2": NodeReachability(
                    server_id="public-b2",
                    data_endpoint=b2_data,
                    control_endpoint=b2_control,
                    reachable_from=frozenset({"public-b2"}),
                    connection_owner_manager_id="public-b2",
                    connection_owner_control_endpoint=b2_control,
                    observed_at=now,
                    expires_at=now + 60,
                    online=True,
                ),
            },
            now=now,
        )
        transfer = coordinator.requests.require(access.transfer_id)
        attempt = coordinator.attempts.require(access.attempt_id)
        retry = coordinator.prepare_download(
            DownloadRequest(
                idempotency_key="three-node-source-push",
                principal="alice",
                storage_server_id="office-a",
                job_id="job-private",
                artifact_name="result.bin",
                expected_size=len(raw),
                expected_sha256=digest,
                expires_at=now + 600,
            ),
            observations={
                "office-a": NodeReachability(
                    server_id="office-a",
                    data_endpoint=observed.data_endpoint,
                    control_endpoint="",
                    reachable_from=observed.reachable_from,
                    connection_owner_manager_id="public-b1",
                    connection_owner_control_endpoint=b1_control,
                    observed_at=now,
                    expires_at=now + 60,
                    online=True,
                ),
                "public-b2": NodeReachability(
                    server_id="public-b2",
                    data_endpoint=b2_data,
                    control_endpoint=b2_control,
                    reachable_from=frozenset({"public-b2"}),
                    connection_owner_manager_id="public-b2",
                    connection_owner_control_endpoint=b2_control,
                    observed_at=now,
                    expires_at=now + 60,
                    online=True,
                ),
            },
            now=now + 0.01,
        )
        assert retry.transfer_id == transfer.transfer_id
        assert retry.attempt_id == attempt.attempt_id
        received = agent.poll_once(timeout=0)
        assert len(received) == 1
        source_push = SourcePushExecutor(
            server_id="office-a",
            replicas=TransferReplicaStore(office_db, server_id="office-a"),
            key=office_key,
            enrollment_token="cluster-enroll",
            origin_resolver=lambda _transfer: source_file,
        )
        executor = TransferCommandExecutor(
            inbox=inbox,
            source_push=source_push,
            claimant="office-a-executor",
            retry_delay=0.1,
        )
        failure: list[BaseException] = []

        def run_source() -> None:
            try:
                executor.run_once()
            except BaseException as exc:  # surfaced in the main test thread
                failure.append(exc)

        source_thread = threading.Thread(target=run_source, daemon=True)
        source_thread.start()
        request = Request(
            b2_data + access.path,
            headers={"Authorization": f"Bearer {access.bearer}"},
        )
        with urlopen(request, timeout=10) as response:
            received_bytes = response.read()
        source_thread.join(timeout=10)

    assert not source_thread.is_alive()
    assert failure == []
    assert received_bytes == raw
    assert inbox.claim(claimant="verify") == []
    assert list((tmp_path / "public-b2-staging").rglob("*.bin")) == []


def test_source_hash_failure_happens_before_requesting_producer_capability(
    tmp_path,
) -> None:
    source = tmp_path / "corrupt.bin"
    source.write_bytes(b"corrupt")
    now = time.time()
    transfer = TransferRecord(
        transfer_id="transfer-1",
        idempotency_key="source-integrity",
        operation=TransferOperation.DOWNLOAD,
        status=TransferStatus.DISPATCHED,
        principal="alice",
        request_owner_manager_id="public-b2",
        relay_owner_manager_id="public-b2",
        connection_owner_manager_id="public-b1",
        source_server_id="office-a",
        destination_server_id="public-b2",
        storage_server_id="office-a",
        job_id="job-1",
        artifact_name="result.bin",
        expected_size=7,
        expected_sha256=hashlib.sha256(b"expected").hexdigest(),
        attempt=1,
        created_at=now,
        updated_at=now,
        expires_at=now + 600,
    )
    attempt = TransferAttemptRecord(
        attempt_id="attempt-1",
        attempt_key="transfer-1:1",
        transfer_id="transfer-1",
        ordinal=1,
        mode=TransferMode.SOURCE_PUSH,
        status=AttemptStatus.PLANNED,
        relay_owner_manager_id="public-b2",
        connection_owner_manager_id="public-b1",
        source_server_id="office-a",
        destination_server_id="public-b2",
        resume_offset=0,
        expected_size=7,
        expected_sha256=transfer.expected_sha256,
        created_at=now,
        updated_at=now,
        expires_at=now + 600,
        last_error="",
        routes=AttemptRouteSnapshot(
            relay_data_endpoint="http://public-b2:7997",
            request_owner_control_endpoint="http://127.0.0.1:1",
            connection_owner_control_endpoint="http://public-b1:7998",
        ),
    )
    command = TransferCommandRecord(
        command_id="command-1",
        transfer_id="transfer-1",
        attempt_id="attempt-1",
        command_type="source.push",
        target_server_id="office-a",
        sequence=1,
        payload={
            "schema_version": 1,
            "context": transfer_context_payload(transfer, attempt),
        },
        payload_hash="hash",
        status="leased",
        delivery_attempt=1,
        lease_owner="executor",
        lease_expires_at=now + 30,
        received_at=now,
        updated_at=now,
        expires_at=now + 600,
        last_error="",
    )
    executor = SourcePushExecutor(
        server_id="office-a",
        replicas=TransferReplicaStore(
            tmp_path / "office.sqlite", server_id="office-a",
        ),
        key=NodeKey.load_or_create(
            tmp_path / "office.key", node_id="office-a",
        ),
        enrollment_token="unused",
        origin_resolver=lambda _transfer: source,
    )

    with pytest.raises(IntegrityError, match="SHA-256"):
        executor.execute(command)
