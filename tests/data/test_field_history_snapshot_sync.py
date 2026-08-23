from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tools.data.field_history import _create_schema
from tools.data.field_history_agent_ingest import ensure_agent_event_schema
from tools.migrations import sync_field_history_snapshot as sync


def _source_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        _create_schema(connection)
        ensure_agent_event_schema(connection)
        connection.execute(
            """
            INSERT INTO historical_field_values
            (provider, source_key, instrument, instrument_label, instrument_type,
             scope_type, exchange, field_name, effective_trading_day,
             effective_timestamp, value, value_type, previous_value,
             previous_value_type, previous_value_note, contract_codes,
             contract_scope_type, contract_code_start, contract_code_end,
             change_type, source_url, source_date, source_notice_id, raw_note)
            VALUES
            ('CZCE', 'event/1', 'AP', 'Apple', 'future', 'product', 'CZCE',
             'OpenRatioByVolume', '2025-01-02', '2025-01-01T15:00:00',
             '5', 'float', NULL, '', '', '[]', 'all', '', '', 'baseline',
             '', '2025-01-01', 'notice-1', '')
            """
        )
        connection.execute(
            """
            INSERT INTO agent_field_change_events
            (event_id, data_source, field_group, source_url, source_accessed_at,
             agent_name, requester_key_hash, instrument, instrument_label,
             instrument_type, scope_type, exchange, field_name,
             effective_trading_day, effective_timestamp, value_json,
             previous_value_json, previous_value_type, previous_value_note,
             contract_codes_json, contract_scope_type, contract_code_start,
             contract_code_end, change_type, source_notice_id, raw_note,
             evidence_text, parser_notes, created_at)
            VALUES
            ('event-1', 'CZCE', 'transaction_fee', '', '2025-01-01', 'agent',
             'hash', 'AP', 'Apple', 'future', 'product', 'CZCE',
             'OpenRatioByVolume', '2025-01-02', '2025-01-01T15:00:00',
             '5', NULL, '', '', '[]', 'all', '', '', 'baseline', 'notice-1',
             '', '', '', 1.0)
            """
        )


def _fake_materialize(destination_path: Path) -> None:
    with sqlite3.connect(destination_path) as connection:
        for table in sync.MATERIALIZED_TABLES:
            connection.execute(f'CREATE TABLE "{table}" (value TEXT)')


def test_snapshot_install_replaces_only_field_history_domain(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.sqlite"
    snapshot = tmp_path / "snapshot.sqlite"
    destination = tmp_path / "destination.sqlite"
    backup = tmp_path / "backup.sqlite"
    _source_database(source)
    with sqlite3.connect(destination) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("CREATE TABLE server_local_state (value TEXT)")
        connection.execute("INSERT INTO server_local_state VALUES ('preserved')")
        _create_schema(connection)
        ensure_agent_event_schema(connection)
    manifest = sync.export_snapshot(source, snapshot)
    monkeypatch.setattr(sync, "_materialize", _fake_materialize)

    installed = sync.install_snapshot(snapshot, destination, backup, apply=True)

    assert installed == manifest
    assert manifest["table_counts"] == {
        "agent_field_change_events": 1,
        "historical_field_values": 1,
    }
    with sqlite3.connect(destination) as connection:
        assert (
            connection.execute("SELECT value FROM server_local_state").fetchone()[0]
            == "preserved"
        )
        assert (
            connection.execute(
                "SELECT instrument FROM historical_field_values"
            ).fetchone()[0]
            == "AP"
        )
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_snapshot_install_restores_backup_when_materialization_fails(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.sqlite"
    snapshot = tmp_path / "snapshot.sqlite"
    destination = tmp_path / "destination.sqlite"
    backup = tmp_path / "backup.sqlite"
    _source_database(source)
    with sqlite3.connect(destination) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("CREATE TABLE server_local_state (value TEXT)")
        connection.execute("INSERT INTO server_local_state VALUES ('before')")
        _create_schema(connection)
        ensure_agent_event_schema(connection)
    sync.export_snapshot(source, snapshot)
    monkeypatch.setattr(
        sync, "_materialize", lambda _: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    with pytest.raises(RuntimeError, match="boom"):
        sync.install_snapshot(snapshot, destination, backup, apply=True)

    with sqlite3.connect(destination) as connection:
        assert (
            connection.execute("SELECT value FROM server_local_state").fetchone()[0]
            == "before"
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM historical_field_values"
            ).fetchone()[0]
            == 0
        )
