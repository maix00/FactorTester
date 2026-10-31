import hashlib
import json
import os
import sqlite3

import pytest

from scripts.migrations.keycloak_profile_inventory import build_inventory, main, read_cache, read_postgres, read_sqlite


def _db(path):
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE account_domain_entities(principal TEXT, entity_type TEXT, entity_id TEXT,
            payload_json TEXT, deleted INTEGER, origin_manager_id TEXT);
        CREATE TABLE account_domain_outbox(principal TEXT, entity_type TEXT, entity_id TEXT);
        CREATE TABLE account_domain_conflicts(principal TEXT, entity_type TEXT, entity_id TEXT, status TEXT);
        CREATE TABLE manager_agent_profile_conversation_sharing(principal TEXT, profile_id TEXT, share_to_parent INTEGER);
        CREATE TABLE manager_profile_runtime_bindings(principal TEXT, profile_id TEXT);
        CREATE TABLE manager_profile_agent_claims(principal TEXT, profile_id TEXT);
        """)
        profile = {"profile_id": "work", "visibility": "authorized", "authorized_users": ["bob"],
                   "session_binding": {"principal_ref": "alice"},
                   "token": "do-not-export", "conversation": "private text"}
        db.execute("INSERT INTO account_domain_entities VALUES (?,?,?,?,?,?)",
                   ("alice", "profile", "work", json.dumps(profile), 0, "manager-a"))
        db.execute("INSERT INTO manager_agent_profile_conversation_sharing VALUES (?,?,?)", ("alice", "work", 1))
        db.execute("INSERT INTO manager_profile_runtime_bindings VALUES (?,?)", ("alice", "runtime-only"))
        db.execute("INSERT INTO account_domain_outbox VALUES (?,?,?)", ("alice", "profile", "outbox-only"))
        db.execute("INSERT INTO account_domain_conflicts VALUES (?,?,?,?)", ("alice", "profile", "work", "open"))


def _cache(path, value):
    path.mkdir()
    name = hashlib.sha256(value["principal"].encode()).hexdigest() + ".json"
    (path / name).write_text(json.dumps(value), encoding="utf-8")


def test_read_only_inventory_preserves_conflicts_and_omits_conversation_content(tmp_path):
    db_path = tmp_path / "db.sqlite"
    _db(db_path)
    cache = tmp_path / "cache"
    _cache(cache, {"principal": "alice", "profiles": [{"profile_id": "work", "visibility": "private",
        "token": "do-not-export", "session_binding": {"principal_ref": "alice"}}],
        "pending_profile_ids": ["orphan-cache"]})
    rows, pending, conflicts, sharing, references = read_sqlite(db_path, principals=["alice"])
    cached, cache_pending = read_cache(cache, principals=["alice"])
    inventory = build_inventory(rows + cached, manager_id="manager-a", pending=pending | cache_pending,
        conflicts=conflicts, sharing=sharing, referenced=references, principals=["alice"])
    objects = {row["profile_id"]: row for row in inventory["objects"]}
    assert set(objects) == {"work", "runtime-only", "outbox-only", "orphan-cache"}
    assert {"projection_authorization_conflict", "open_synchronization_conflict",
            "conversation_sharing_policy_not_verified", "local_remote_conversation_policy_differs"}.issubset(objects["work"]["reasons"])
    assert objects["work"]["legacy_share_to_parent"] is True
    assert "missing_profile_projection" in objects["orphan-cache"]["reasons"]
    assert "pending_synchronization" in objects["orphan-cache"]["reasons"]
    assert "missing_profile_projection" in objects["runtime-only"]["reasons"]
    assert inventory["summary"]["cutover_ready"] is False
    assert inventory["postgres_checked"] is False and inventory["cross_source_atomic"] is False
    assert "do-not-export" not in json.dumps(inventory)
    assert "private text" not in json.dumps(inventory)
    # Deterministic and independent of projection read order.
    assert inventory["sha256"] == build_inventory(list(reversed(rows + cached)), manager_id="manager-a",
        pending=pending | cache_pending, conflicts=conflicts, sharing=sharing, referenced=references,
        principals=["alice"])["sha256"]


def test_cache_rejects_wrong_owner_filename_and_symlinks(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    name = hashlib.sha256(b"alice").hexdigest() + ".json"
    (cache / name).write_text(json.dumps({"principal": "bob", "profiles": []}))
    with pytest.raises(ValueError, match="filename"):
        read_cache(cache, principals=["alice"])
    (cache / name).unlink()
    os.symlink(tmp_path / "outside", cache / name)
    with pytest.raises(OSError):
        read_cache(cache, principals=["alice"])


def test_cache_rejects_invalid_sharing_values(tmp_path):
    cache = tmp_path / "cache"
    _cache(cache, {"principal": "alice", "profiles": [{"profile_id": "work", "conversation_sharing": "yes"}]})
    with pytest.raises(ValueError, match="sharing"):
        read_cache(cache, principals=["alice"])


def test_inventory_requires_and_enforces_principal_scope(tmp_path):
    db_path = tmp_path / "db.sqlite"
    _db(db_path)
    with sqlite3.connect(db_path) as db:
        db.execute("INSERT INTO account_domain_entities VALUES (?,?,?,?,?,?)", ("bob", "profile", "other",
            json.dumps({"profile_id": "other"}), 0, "manager-a"))
        db.execute("INSERT INTO account_domain_outbox VALUES (?,?,?)", ("bob", "profile", "other"))
    with pytest.raises(ValueError, match="scope"):
        read_sqlite(db_path, principals=[])
    rows, pending, conflicts, sharing, referenced = read_sqlite(db_path, principals=["alice"])
    assert all(row["principal"] == "alice" for row in rows)
    assert all(owner == "alice" for owner, _ in pending | conflicts | set(sharing) | referenced)
    with pytest.raises(ValueError, match="outside"):
        build_inventory(rows, manager_id="manager-a", pending=pending, conflicts=conflicts, sharing=sharing,
                        referenced=referenced, principals=["bob"])


def test_cli_output_is_private_and_prints_aggregate_only(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "db.sqlite"
    _db(db_path)
    cache = tmp_path / "cache"
    _cache(cache, {"principal": "alice", "profiles": []})
    directory = tmp_path / "reviewed.json"
    directory.write_text(json.dumps({"accounts": [{"username": "alice"}]}))
    output = tmp_path / "inventory.json"
    monkeypatch.setattr("sys.argv", ["inventory", "--database", str(db_path), "--cache-root", str(cache),
        "--manager-id", "manager-a", "--reviewed-directory", str(directory), "--output", str(output)])
    main()
    assert (output.stat().st_mode & 0o777) == 0o600
    assert "alice" not in capsys.readouterr().out
    assert json.loads(output.read_text())["principal_scope"] == ["alice"]
    with pytest.raises(FileExistsError):
        main()


def test_postgres_inventory_uses_scoped_readonly_snapshot_and_keeps_envelope_conflicts():
    from types import SimpleNamespace
    columns = ["principal", "profile_id", "deleted", "origin_manager_id", "binding_profile_id",
        "payload_type", "binding_type", "binding_owner", "owner_identity_id", "visibility", "profile_visibility", "authorized_users",
        "conversation_sharing", "envelope_visibility", "envelope_authorized_users"]
    record = ("alice", "work", False, "manager-a", "work", "object", "object", "alice", None,
              "private", None, [], None, "authorized", ["bob"])
    class Cursor:
        description = [SimpleNamespace(name=name) for name in columns]
        def __init__(self, rows): self.rows = list(rows)
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def execute(self, query, params):
            assert params == (["alice"], 100001)
            assert "principal = ANY(%s)" in query and "SELECT *" not in query
        def fetchmany(self, _limit):
            rows, self.rows = self.rows, []
            return rows
    class Connection:
        def __init__(self): self.commands = []
        def transaction(self): return self
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def execute(self, query):
            self.commands.append(query)
            return SimpleNamespace(fetchone=lambda: ("db", "127.0.0.1", 5432, "started", "snapshot"))
        def cursor(self, *, name):
            return Cursor([record] if name.endswith("1") else [])
    connection = Connection()
    rows, snapshot = read_postgres(connection, principals=["alice"])
    assert connection.commands[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert [row["source"] for row in rows] == ["postgres_account_payload", "postgres_account_acl"]
    assert set(snapshot) == {"database_observation_sha256", "transaction_snapshot_sha256"}
    inventory = build_inventory(rows, manager_id="manager-a", pending=set(), conflicts=set(),
        sharing={}, referenced=set(), principals=["alice"], postgres_snapshot=snapshot)
    assert inventory["postgres_checked"] is True and inventory["cross_source_atomic"] is False
    assert "projection_authorization_conflict" in inventory["objects"][0]["reasons"]
    assert "postgres_snapshot_not_verified" not in inventory["objects"][0]["reasons"]
    assert "client_source_not_verified" in inventory["objects"][0]["reasons"]
