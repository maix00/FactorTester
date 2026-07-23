"""Immutable, scope-bound Research Graph object persistence."""

from __future__ import annotations

from copy import deepcopy

import orjson
import pytest

from server.services.research_graph.graph_objects import (
    MAX_GRAPH_OBJECT_BYTES,
    create_graph_object_schema,
    insert_graph_objects,
    load_graph_objects,
    prepare_graph_object,
)
from tools.data.sqlite.db import connect_sqlite


def test_prepared_object_round_trips_by_canonical_reference(tmp_path) -> None:
    path = tmp_path / "graph-objects.sqlite"
    first = prepare_graph_object(
        "alice",
        "instance-1",
        "research_cycle_checkpoint",
        {"z": 2, "a": {"value": 1}},
    )
    equivalent = prepare_graph_object(
        "alice",
        "instance-1",
        "research_cycle_checkpoint",
        {"a": {"value": 1}, "z": 2},
    )

    assert first["object_ref"] == equivalent["object_ref"]
    assert first["object_ref"].startswith("research-graph-object:sha256:")
    with connect_sqlite(path) as conn:
        create_graph_object_schema(conn)
        insert_graph_objects(conn, [first])
        loaded = load_graph_objects(
            conn,
            "alice",
            "instance-1",
            [first["object_ref"]],
        )

    assert loaded == {
        first["object_ref"]: {"a": {"value": 1}, "z": 2},
    }


def test_graph_object_schema_has_one_hash_keyed_relation(tmp_path) -> None:
    path = tmp_path / "graph-objects.sqlite"
    with connect_sqlite(path) as conn:
        create_graph_object_schema(conn)
        columns = conn.execute(
            "PRAGMA table_info(research_graph_objects)"
        ).fetchall()
        tables = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()

    assert [row["name"] for row in columns] == [
        "object_hash",
        "owner",
        "instance_id",
        "object_kind",
        "object_json",
        "byte_size",
        "created_at",
    ]
    assert columns[0]["pk"] == 1
    assert [row["name"] for row in tables] == ["research_graph_objects"]


def test_insert_is_immutable_and_performs_no_read(tmp_path) -> None:
    path = tmp_path / "graph-objects.sqlite"
    first = prepare_graph_object(
        "alice", "instance-1", "claim", {"claim_id": "claim-1"}
    )
    duplicate = prepare_graph_object(
        "alice", "instance-1", "claim", {"claim_id": "claim-1"}
    )
    duplicate["created_at"] = first["created_at"] + 10
    statements: list[str] = []

    with connect_sqlite(path) as conn:
        create_graph_object_schema(conn)
        conn.set_trace_callback(statements.append)
        insert_graph_objects(conn, [first, duplicate])
        conn.set_trace_callback(None)
        row = conn.execute(
            "SELECT COUNT(*) AS count, created_at "
            "FROM research_graph_objects"
        ).fetchone()

    assert row["count"] == 1
    assert row["created_at"] == first["created_at"]
    normalized = [" ".join(item.upper().split()) for item in statements]
    assert normalized
    assert not any(item.startswith("SELECT") for item in normalized)
    assert len([
        item for item in normalized if item.startswith("INSERT OR IGNORE")
    ]) == 2


def test_insert_rejects_a_tampered_prepared_object_without_writing(
    tmp_path,
) -> None:
    path = tmp_path / "graph-objects.sqlite"
    prepared = prepare_graph_object(
        "alice", "instance-1", "claim", {"claim_id": "claim-1"}
    )
    tampered = deepcopy(prepared)
    tampered["object_json"] = '{"claim_id":"claim-2"}'

    with connect_sqlite(path) as conn:
        create_graph_object_schema(conn)
        with pytest.raises(ValueError, match="hash mismatch"):
            insert_graph_objects(conn, [tampered])
        count = conn.execute(
            "SELECT COUNT(*) FROM research_graph_objects"
        ).fetchone()[0]

    assert count == 0


def test_insert_remains_in_the_callers_transaction(tmp_path) -> None:
    path = tmp_path / "graph-objects.sqlite"
    prepared = prepare_graph_object(
        "alice", "instance-1", "claim", {"claim_id": "claim-1"}
    )
    with connect_sqlite(path) as conn:
        create_graph_object_schema(conn)
    with connect_sqlite(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        insert_graph_objects(conn, [prepared])
        assert conn.in_transaction is True
        conn.rollback()
        with pytest.raises(KeyError, match="not found"):
            load_graph_objects(
                conn,
                "alice",
                "instance-1",
                [prepared["object_ref"]],
            )


def test_load_is_scope_bound_and_hashes_the_scope(tmp_path) -> None:
    path = tmp_path / "graph-objects.sqlite"
    alice = prepare_graph_object(
        "alice", "instance-1", "claim", {"claim_id": "claim-1"}
    )
    bob = prepare_graph_object(
        "bob", "instance-1", "claim", {"claim_id": "claim-1"}
    )
    other_instance = prepare_graph_object(
        "alice", "instance-2", "claim", {"claim_id": "claim-1"}
    )
    assert len({
        alice["object_ref"],
        bob["object_ref"],
        other_instance["object_ref"],
    }) == 3

    with connect_sqlite(path) as conn:
        create_graph_object_schema(conn)
        insert_graph_objects(conn, [alice])
        with pytest.raises(KeyError, match="not found"):
            load_graph_objects(
                conn, "bob", "instance-1", [alice["object_ref"]]
            )
        with pytest.raises(KeyError, match="not found"):
            load_graph_objects(
                conn, "alice", "instance-2", [alice["object_ref"]]
            )


def test_batch_load_uses_one_select_and_verifies_kind(tmp_path) -> None:
    path = tmp_path / "graph-objects.sqlite"
    claim = prepare_graph_object(
        "alice", "instance-1", "claim", {"claim_id": "claim-1"}
    )
    obligation = prepare_graph_object(
        "alice",
        "instance-1",
        "obligation",
        {"obligation_id": "obligation-1"},
    )
    statements: list[str] = []

    with connect_sqlite(path) as conn:
        create_graph_object_schema(conn)
        insert_graph_objects(conn, [claim, obligation])
        conn.set_trace_callback(statements.append)
        loaded = load_graph_objects(
            conn,
            "alice",
            "instance-1",
            [claim["object_ref"], obligation["object_ref"]],
            expected_kinds={
                claim["object_ref"]: "claim",
                obligation["object_ref"]: "obligation",
            },
        )
        conn.set_trace_callback(None)
        with pytest.raises(ValueError, match="kind mismatch"):
            load_graph_objects(
                conn,
                "alice",
                "instance-1",
                [claim["object_ref"]],
                expected_kinds={claim["object_ref"]: "obligation"},
            )

    assert set(loaded) == {claim["object_ref"], obligation["object_ref"]}
    normalized = [" ".join(item.upper().split()) for item in statements]
    assert len([item for item in normalized if item.startswith("SELECT")]) == 1


def test_load_rejects_tampered_storage_and_non_exact_refs(tmp_path) -> None:
    path = tmp_path / "graph-objects.sqlite"
    prepared = prepare_graph_object(
        "alice", "instance-1", "claim", {"claim_id": "claim-1"}
    )
    with connect_sqlite(path) as conn:
        create_graph_object_schema(conn)
        insert_graph_objects(conn, [prepared])
        conn.execute(
            "UPDATE research_graph_objects "
            "SET object_json='{\"claim_id\":\"claim-2\"}'"
        )
        with pytest.raises(ValueError, match="hash mismatch"):
            load_graph_objects(
                conn,
                "alice",
                "instance-1",
                [prepared["object_ref"]],
            )
        for ref in (
            prepared["object_ref"] + ":extra",
            prepared["object_ref"].upper(),
            prepared["object_hash"],
        ):
            with pytest.raises(ValueError, match="ref is invalid"):
                load_graph_objects(conn, "alice", "instance-1", [ref])


def test_load_rejects_tampered_size_metadata(tmp_path) -> None:
    path = tmp_path / "graph-objects.sqlite"
    prepared = prepare_graph_object(
        "alice", "instance-1", "claim", {"claim_id": "claim-1"}
    )
    with connect_sqlite(path) as conn:
        create_graph_object_schema(conn)
        insert_graph_objects(conn, [prepared])
        conn.execute(
            "UPDATE research_graph_objects SET byte_size=byte_size + 1"
        )
        with pytest.raises(ValueError, match="byte_size mismatch"):
            load_graph_objects(
                conn,
                "alice",
                "instance-1",
                [prepared["object_ref"]],
            )


def test_prepare_accepts_32_kib_and_rejects_one_byte_more() -> None:
    empty_size = len(orjson.dumps({"payload": ""}))
    prepared = prepare_graph_object(
        "alice",
        "instance-1",
        "checkpoint",
        {"payload": "x" * (MAX_GRAPH_OBJECT_BYTES - empty_size)},
    )
    assert prepared["byte_size"] == MAX_GRAPH_OBJECT_BYTES

    with pytest.raises(ValueError, match="exceeds 32 KiB"):
        prepare_graph_object(
            "alice",
            "instance-1",
            "checkpoint",
            {
                "payload": "x" * (
                    MAX_GRAPH_OBJECT_BYTES - empty_size + 1
                ),
            },
        )
