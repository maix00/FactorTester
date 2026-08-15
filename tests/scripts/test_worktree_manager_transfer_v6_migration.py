from __future__ import annotations

import sqlite3

from server.manager.storage.transfers import TransferStore


def _legacy_database(path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE transfer_requests (
                transfer_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                operation TEXT NOT NULL,
                status TEXT NOT NULL,
                principal TEXT NOT NULL,
                request_owner_manager_id TEXT NOT NULL,
                relay_owner_manager_id TEXT NOT NULL,
                connection_owner_manager_id TEXT NOT NULL DEFAULT '',
                source_server_id TEXT NOT NULL,
                destination_server_id TEXT NOT NULL,
                storage_server_id TEXT NOT NULL,
                job_id TEXT NOT NULL DEFAULT '',
                artifact_name TEXT NOT NULL DEFAULT '',
                expected_size INTEGER NOT NULL,
                expected_sha256 TEXT NOT NULL DEFAULT '',
                attempt INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );
            CREATE TABLE transfer_attempts (
                attempt_id TEXT PRIMARY KEY,
                attempt_key TEXT NOT NULL UNIQUE,
                transfer_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                relay_owner_manager_id TEXT NOT NULL,
                connection_owner_manager_id TEXT NOT NULL DEFAULT '',
                source_server_id TEXT NOT NULL,
                destination_server_id TEXT NOT NULL,
                relay_data_endpoint TEXT NOT NULL DEFAULT '',
                source_data_endpoint TEXT NOT NULL DEFAULT '',
                source_control_endpoint TEXT NOT NULL DEFAULT '',
                destination_data_endpoint TEXT NOT NULL DEFAULT '',
                destination_control_endpoint TEXT NOT NULL DEFAULT '',
                request_owner_control_endpoint TEXT NOT NULL DEFAULT '',
                connection_owner_control_endpoint TEXT NOT NULL DEFAULT '',
                resume_offset INTEGER NOT NULL,
                expected_size INTEGER NOT NULL,
                expected_sha256 TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                last_error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE transfer_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO transfer_meta VALUES ('schema_version', '5');
            INSERT INTO transfer_requests VALUES (
                'transfer-1', 'legacy-key', 'download', 'dispatched', 'alice',
                'public-b2', 'public-b2', 'public-b1', 'office-a', 'public-b2',
                'office-a', 'job-1', 'result.bin', 6, '', 1, 100, 101, 200
            );
            INSERT INTO transfer_attempts VALUES (
                'attempt-1', 'legacy-key:1', 'transfer-1', 1, 'source_push',
                'waiting_consumer', 'public-b2', 'public-b1', 'office-a',
                'public-b2', 'https://public-b2:7997',
                'https://office-a:7997', 'https://office-a:7998',
                'https://public-b2:7997', 'https://public-b2:7998',
                'https://public-b2:7998', 'https://public-b1:7998',
                0, 6, '', 100, 101, 200, ''
            );
            """
        )


def test_v5_nat_attempt_is_archived_and_never_loaded_as_wireguard_route(
    tmp_path,
) -> None:
    path = tmp_path / "transfers.sqlite"
    _legacy_database(path)

    store = TransferStore(path, server_id="public-b2")
    restored = store.require("transfer-1")

    assert restored.status.value == "failed"
    assert restored.attempt == 0
    with sqlite3.connect(path) as connection:
        version = connection.execute(
            "SELECT value FROM transfer_meta WHERE key='schema_version'"
        ).fetchone()[0]
        active = connection.execute(
            "SELECT count(*) FROM transfer_attempts"
        ).fetchone()[0]
        archived = connection.execute(
            "SELECT legacy_mode, legacy_status, reason "
            "FROM transfer_legacy_attempts WHERE attempt_id='attempt-1'"
        ).fetchone()
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(transfer_attempts)"
            ).fetchall()
        }

    assert version == "8"
    assert active == 0
    assert archived[0:2] == ("source_push", "waiting_consumer")
    assert "WireGuard-direct" in archived[2]
    assert "source_peer_data_endpoint" in columns
    assert "relay_data_endpoint" not in columns


def test_v6_endpoint_registry_upgrades_additively_to_signed_advertisements(
    tmp_path,
) -> None:
    path = tmp_path / "transfers.sqlite"
    store = TransferStore(path, server_id="node-a")
    del store
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE transfer_meta SET value='6' WHERE key='schema_version'"
        )
        connection.execute("DROP TABLE transfer_node_advertisement_state")
        connection.execute("DROP TABLE transfer_node_advertisement_nonces")
        connection.execute("DROP TABLE transfer_node_advertisement_clock")

    TransferStore(path, server_id="node-a")

    with sqlite3.connect(path) as connection:
        version = connection.execute(
            "SELECT value FROM transfer_meta WHERE key='schema_version'"
        ).fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert version == "8"
    assert "transfer_node_advertisement_nonces" in tables
    assert "transfer_node_advertisement_state" in tables
    assert "transfer_node_advertisement_clock" in tables


def test_future_schema_version_is_rejected_without_modification(tmp_path) -> None:
    path = tmp_path / "future.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE transfer_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO transfer_meta VALUES ('schema_version', '99')"
        )

    try:
        TransferStore(path, server_id="node-a")
    except RuntimeError as exc:
        assert "unsupported transfer schema version 99" in str(exc)
    else:  # pragma: no cover - documents the required startup failure
        raise AssertionError("future schema unexpectedly opened")
