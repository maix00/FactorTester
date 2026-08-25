from __future__ import annotations

import json
import sqlite3

import pytest

from tools.factors.formula_identity import (
    freeze_factor_identity,
    require_frozen_factor,
)
from tools.migrations.migrate_factor_formula_identity import (
    IncompatibleFactorConfiguration,
    backfill_current_factor_source_versions,
    migrate_configuration_database,
    migrate_editable_configuration_payload,
)


def test_source_version_backfill_only_records_current_semantic_fingerprint() -> None:
    fingerprint = "c" * 64
    versions: dict[tuple[str, str, str, str], dict] = {}
    recorded = []

    def load(kind, owner, factor_id, value):
        return versions.get((kind, owner, factor_id, value))

    def record(kind, owner, factor_id, source_code, **kwargs):
        recorded.append((kind, owner, factor_id, source_code, kwargs))
        value = {"family_formula_fingerprint": kwargs["family_formula_fingerprint"]}
        versions[(kind, owner, factor_id, kwargs["family_formula_fingerprint"])] = value
        return value

    rows = [{
        "source_kind": "custom",
        "owner_username": "alice",
        "factor_id": "Momentum",
        "source_code": "class Momentum(FactorFamily):\n    pass\n",
    }]
    dry_run = backfill_current_factor_source_versions(
        source_rows=rows,
        fingerprint_resolver=lambda *_args: fingerprint,
        version_loader=load,
        version_recorder=record,
    )
    applied = backfill_current_factor_source_versions(
        apply=True,
        source_rows=rows,
        fingerprint_resolver=lambda *_args: fingerprint,
        version_loader=load,
        version_recorder=record,
    )
    repeated = backfill_current_factor_source_versions(
        apply=True,
        source_rows=rows,
        fingerprint_resolver=lambda *_args: fingerprint,
        version_loader=load,
        version_recorder=record,
    )

    assert dry_run == {"eligible": 1, "planned": 1, "migrated": 0, "errors": []}
    assert applied == {"eligible": 1, "planned": 1, "migrated": 1, "errors": []}
    assert repeated == {"eligible": 1, "planned": 0, "migrated": 0, "errors": []}
    assert recorded[0][4]["family_formula_fingerprint"] == fingerprint


def _resolved(record: dict) -> dict:
    assert record["params"] == {"N": "20d"}
    return freeze_factor_identity(
        owner_ref="principal:alice",
        family_alias="Momentum",
        factor_alias="Momentum|N:20d",
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint="b" * 64,
        params={"N": "20d"},
    )


def test_editable_configuration_migrates_factor_and_all_exact_references() -> None:
    payload = {
        "schema_version": 1,
        "shared": {"factors": [{
            "factor_ref": "factor:v1:legacy",
            "factor_owner_ref": "principal:alice",
            "factor_family_alias": "Momentum",
            "factor_alias": "Momentum:0",
            "params": {"N": "20d"},
            "factor_git_commit": "deadbeef",
        }]},
        "analyses": {"ic": {"factor_candidate_refs": ["factor:v1:legacy"]}},
        "ui": {"ic": {"selected": "factor:v1:legacy"}},
    }

    migrated = migrate_editable_configuration_payload(payload, resolver=_resolved)

    assert migrated["schema_version"] == 2
    factor = migrated["shared"]["factors"][0]
    assert factor["alias"] == "Momentum|N:20d"
    assert "factor_git_commit" not in factor
    assert migrated["analyses"]["ic"]["factor_candidate_refs"] == [
        factor["ref"],
    ]
    assert migrated["ui"]["ic"]["selected"] == factor["ref"]


def test_editable_configuration_fails_atomically_when_factor_is_ambiguous() -> None:
    payload = {
        "schema_version": 1,
        "shared": {"factors": [{
            "factor_ref": "factor:v1:legacy",
            "factor_owner_ref": "principal:alice",
            "factor_family_alias": "Momentum",
            "factor_alias": "Momentum:0",
        }]},
        "analyses": {},
        "ui": {},
    }

    with pytest.raises(IncompatibleFactorConfiguration, match="parameters"):
        migrate_editable_configuration_payload(payload, resolver=_resolved)


def test_historical_or_already_v2_payload_is_not_runtime_migrated() -> None:
    with pytest.raises(IncompatibleFactorConfiguration, match="schema 1"):
        migrate_editable_configuration_payload(
            {"schema_version": 2, "shared": {}, "analyses": {}, "ui": {}},
            resolver=_resolved,
        )


def test_explicit_database_migration_updates_editable_rows_not_historical_runs(
    tmp_path,
) -> None:
    database = tmp_path / "manager.sqlite3"
    payload = {
        "schema_version": 1,
        "shared": {"factors": [{
            "factor_ref": "factor:v1:legacy",
            "factor_owner_ref": "principal:alice",
            "factor_family_alias": "Momentum",
            "factor_alias": "Momentum:0",
            "params": {"N": "20d"},
        }]},
        "analyses": {},
        "ui": {},
    }
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE research_configurations ("
            "configuration_id TEXT PRIMARY KEY, schema_version INTEGER, "
            "revision INTEGER, payload_json TEXT)"
        )
        connection.execute(
            "INSERT INTO research_configurations VALUES (?, ?, ?, ?)",
            ("config-1", 1, 4, json.dumps(payload)),
        )
        connection.execute(
            "CREATE TABLE research_runs (run_id TEXT PRIMARY KEY, run_spec_json TEXT)"
        )
        connection.execute(
            "INSERT INTO research_runs VALUES (?, ?)",
            ("run-1", json.dumps({"configuration": payload})),
        )

    report = migrate_configuration_database(database, resolver=_resolved, apply=True)

    assert report["eligible"] == 1
    assert report["planned"] == 1
    assert report["migrated"] == 1
    assert report["errors"] == []
    assert report["plan_hash"].startswith("sha256:")
    with sqlite3.connect(database) as connection:
        schema, revision, migrated_raw = connection.execute(
            "SELECT schema_version, revision, payload_json "
            "FROM research_configurations"
        ).fetchone()
        historical_raw = connection.execute(
            "SELECT run_spec_json FROM research_runs"
        ).fetchone()[0]
    assert (schema, revision) == (2, 5)
    assert json.loads(migrated_raw)["schema_version"] == 2
    assert json.loads(historical_raw)["configuration"]["schema_version"] == 1


def test_database_migration_commits_recoverable_rows_and_keeps_bad_drafts(
    tmp_path,
) -> None:
    database = tmp_path / "manager.sqlite3"
    valid = {
        "schema_version": 1,
        "shared": {"factors": [{
            "factor_family_alias": "Momentum",
            "factor_alias": "Momentum|N:20d",
            "params": {"N": "20d"},
        }]},
        "analyses": {},
        "ui": {},
    }
    invalid = {
        "schema_version": 1,
        "shared": {"factors": [{"factor_alias": "Missing"}]},
        "analyses": {},
        "ui": {},
    }
    owners: list[str] = []

    def resolve(record: dict) -> dict:
        owners.append(record["configuration_owner"])
        return _resolved(record)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE research_configurations ("
            "configuration_id TEXT PRIMARY KEY, owner TEXT, "
            "schema_version INTEGER, revision INTEGER, payload_json TEXT)"
        )
        connection.executemany(
            "INSERT INTO research_configurations VALUES (?, ?, ?, ?, ?)",
            [
                ("valid", "GTHT@alice@1", 1, 1, json.dumps(valid)),
                ("invalid", "GTHT@alice@1", 1, 1, json.dumps(invalid)),
            ],
        )

    report = migrate_configuration_database(database, resolver=resolve, apply=True)

    assert report["planned"] == 1
    assert report["migrated"] == 1
    assert [item["configuration_id"] for item in report["errors"]] == ["invalid"]
    assert owners == ["GTHT@alice@1"]
    with sqlite3.connect(database) as connection:
        rows = dict(connection.execute(
            "SELECT configuration_id, schema_version FROM research_configurations"
        ).fetchall())
    assert rows == {"valid": 2, "invalid": 1}


def test_explicit_migration_rebuilds_legacy_factor_set_with_principal_owner(
    tmp_path,
) -> None:
    database = tmp_path / "manager.sqlite3"
    payload = {
        "schema_version": 1,
        "shared": {"factors": [{
            "factor_ref": "factor:v1:member",
            "factor_owner_ref": "principal:alice",
            "factor_family_alias": "Momentum",
            "factor_alias": "Momentum|N:20d",
            "params": {"N": "20d"},
        }]},
        "analyses": {},
        "ui": {},
    }
    legacy_set = {
        "schema_version": 1,
        "set_id": "momentum",
        "title_zh": "动量集合",
        "member_refs": ["factor:v1:member"],
    }
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE research_configurations ("
            "configuration_id TEXT PRIMARY KEY, owner TEXT, schema_version INTEGER, "
            "revision INTEGER, payload_json TEXT)"
        )
        connection.execute(
            "INSERT INTO research_configurations VALUES (?, ?, ?, ?, ?)",
            ("config", "alice", 1, 1, json.dumps(payload)),
        )
        connection.execute(
            "CREATE TABLE account_factor_sets ("
            "username TEXT, target_ref TEXT, set_ref TEXT, "
            "payload_json TEXT, updated_at REAL)"
        )
        connection.execute(
            "INSERT INTO account_factor_sets VALUES (?, ?, ?, ?, ?)",
            ("alice", "factor-set:v1:legacy", "factor-set:v1:legacy", json.dumps(legacy_set), 1),
        )

    report = migrate_configuration_database(database, resolver=_resolved, apply=True)

    assert report["factor_sets"] == {
        "eligible": 1, "planned": 1, "migrated": 1, "errors": [],
    }
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute(
            "PRAGMA table_info(account_factor_sets)"
        )}
        owner_ref, raw = connection.execute(
            "SELECT owner_ref, payload_json FROM account_factor_sets"
        ).fetchone()
    assert {"owner_ref", "set_id"}.issubset(columns)
    assert owner_ref == "principal:alice"
    migrated = json.loads(raw)
    assert migrated["ref"].startswith("factor-set:v2:")
    assert migrated["identity"]["members"][0]["ref"].startswith("factor:v2:")


def test_explicit_migration_updates_account_domain_and_writes_control_plan(
    tmp_path,
) -> None:
    database = tmp_path / "manager.sqlite3"
    control_plan = tmp_path / "control-plan.json"
    factor_config = {
        "factor_family_alias": "Momentum",
        "params_list": [{"N": "20d"}],
        "resolved_factors": [{
            "factor_alias": "Momentum:0",
            "source": "custom",
        }],
    }
    legacy_set = {
        "schema_version": 1,
        "target_ref": "factor-set:v1:legacy",
        "member_refs": ["factor:v1:legacy"],
    }
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE research_configurations ("
            "configuration_id TEXT PRIMARY KEY, schema_version INTEGER, "
            "revision INTEGER, payload_json TEXT)"
        )
        connection.execute(
            "CREATE TABLE account_domain_entities ("
            "principal TEXT, entity_type TEXT, entity_id TEXT, "
            "payload_json TEXT, deleted INTEGER, remote_revision INTEGER, "
            "base_revision INTEGER, PRIMARY KEY (principal, entity_type, entity_id))"
        )
        connection.executemany(
            "INSERT INTO account_domain_entities VALUES (?, ?, ?, ?, 0, 3, 3)",
            [
                (
                    "alice", "factor_param_config", "default:Momentum",
                    json.dumps(factor_config),
                ),
                (
                    "alice", "factor_set", "legacy-set",
                    json.dumps(legacy_set),
                ),
            ],
        )

    report = migrate_configuration_database(
        database,
        resolver=_resolved,
        apply=True,
        discard_incompatible=True,
        control_plan_path=control_plan,
    )

    assert report["account_domain"]["eligible"] == 2
    assert report["account_domain"]["planned"] == 2
    assert report["account_domain"]["migrated"] == 2
    assert report["account_domain"]["discarded"] == 1
    assert len(report["account_domain"]["errors"]) == 1
    with sqlite3.connect(database) as connection:
        factor_raw, factor_deleted, factor_revision = connection.execute(
            "SELECT payload_json, deleted, remote_revision "
            "FROM account_domain_entities WHERE entity_type='factor_param_config'"
        ).fetchone()
        set_raw, set_deleted = connection.execute(
            "SELECT payload_json, deleted FROM account_domain_entities "
            "WHERE entity_type='factor_set'"
        ).fetchone()
    factor_payload = json.loads(factor_raw)
    require_frozen_factor(factor_payload["resolved_factors"][0])
    assert factor_payload["schema_version"] == 2
    assert (factor_deleted, factor_revision) == (0, 4)
    assert set_deleted == 1
    assert json.loads(set_raw)["schema_version"] == 2
    plan = json.loads(control_plan.read_text(encoding="utf-8"))["rows"]
    assert len(plan) == 2
    assert {item["expected_revision"] for item in plan} == {3}
