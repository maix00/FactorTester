from __future__ import annotations

import json
import sqlite3

import pytest
from click.testing import CliRunner

from tools.cli.commands.client_catalog import client_catalog
from tools.data.catalog import LocalCatalogStore
from tools.factors.factor_set_identity import freeze_factor_set_identity
from tools.factors.formula_identity import freeze_factor_identity


def _factor_record() -> dict:
    return freeze_factor_identity(
        owner_ref="profile:maxa",
        family_alias="MmRateOfChg",
        factor_alias="MmRateOfChg|P:CA|N:20d|$F:1d",
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint="b" * 64,
        params={"P": "CA", "N": "20d", "$F": "1d"},
    )


def _factor_set_record(factor: dict) -> dict:
    return freeze_factor_set_identity(
        owner_ref="profile:maxa",
        set_id="momentum",
        alias="动量因子集合",
        members=[factor],
    )


def _source(store: LocalCatalogStore) -> None:
    store.upsert_source({
        "source_id": "source:local:test",
        "source_kind": "local",
        "class_path": "Product/Futures/CNFutures",
        "source_revision": "local:1",
    })


def _product(store: LocalCatalogStore, ref: str = "product:SI.GFE") -> None:
    store.upsert_product({
        "product_ref": ref,
        "source_id": "source:local:test",
        "class_path": "Product/Futures/CNFutures",
        "alias": ref.split(":", 1)[1],
        "display_name": "工业硅",
    })


def test_catalog_initializes_wal_database_and_preserves_counts(tmp_path) -> None:
    store = LocalCatalogStore(tmp_path / "FactorTester")

    value = store.initialize()

    assert value["schema_version"] == 2
    assert value["database"].endswith("catalog/catalog.sqlite")
    assert value["products"] == 0
    assert (tmp_path / "FactorTester/catalog/catalog.sqlite-wal").exists() or (
        tmp_path / "FactorTester/catalog/catalog.sqlite"
    ).exists()


def test_group_owned_membership_is_atomic_and_does_not_replace_other_groups(tmp_path) -> None:
    store = LocalCatalogStore(tmp_path / "FactorTester")
    _source(store)
    _product(store)
    store.upsert_product({
        "product_ref": "product:CU.SHF",
        "source_id": "source:local:test",
        "class_path": "Product/Futures/CNFutures",
        "alias": "CU.SHF",
        "display_name": "沪铜",
    })
    for ref, name in (("group:metals", "金属"), ("group:energy", "能源")):
        store.upsert_group({"group_ref": ref, "owner_ref": "alice", "name": name})

    store.replace_group_products(
        "group:metals",
        [{"product_ref": "product:SI.GFE", "valid_from": "2024-01-01"}],
    )
    store.replace_group_products(
        "group:energy",
        [{"product_ref": "product:CU.SHF", "valid_from": "2024-01-01"}],
    )
    store.replace_group_subjects(
        "group:metals",
        [{"subject_kind": "factor", "subject_ref": "factor:sha256:roc"}],
    )

    with pytest.raises(ValueError, match="subject_kind"):
        store.replace_group_subjects(
            "group:metals",
            [{"subject_kind": "factor", "subject_ref": "factor:sha256:roc"}, {}],
        )

    with store.connection() as connection:
        metals_products = connection.execute(
            "SELECT product_ref FROM product_group_products "
            "WHERE group_ref = ?", ("group:metals",)
        ).fetchall()
        energy_products = connection.execute(
            "SELECT product_ref FROM product_group_products "
            "WHERE group_ref = ?", ("group:energy",)
        ).fetchall()
        subjects = connection.execute(
            "SELECT subject_kind, subject_ref FROM product_group_subject_bindings "
            "WHERE group_ref = ?", ("group:metals",)
        ).fetchall()

    assert [row[0] for row in metals_products] == ["product:SI.GFE"]
    assert [row[0] for row in energy_products] == ["product:CU.SHF"]
    assert [tuple(row) for row in subjects] == [("factor", "factor:sha256:roc")]


def test_factor_identities_are_formula_frozen_and_git_is_optional_provenance(tmp_path) -> None:
    store = LocalCatalogStore(tmp_path / "FactorTester")
    factor_record = _factor_record()
    store.upsert_factor(factor_record)
    store.upsert_factor_provenance({
        "ref": factor_record["ref"],
        "repository_ref": "profile:maxa",
        "revision": "abc",
        "blob_hash": "def",
        "relative_path": "custom_factors/MmRateOfChg.py",
        "source_hash": "sha256:source",
    })
    store.upsert_factor_set(_factor_set_record(factor_record))

    with store.connection() as connection:
        factor = connection.execute(
            "SELECT revision, blob_hash FROM factor_workspace_provenance"
        ).fetchone()
        factor_set = connection.execute(
            "SELECT member_count, member_fingerprint FROM factor_sets"
        ).fetchone()
        member = connection.execute(
            "SELECT factor_ref FROM factor_set_members"
        ).fetchone()

    assert tuple(factor) == ("abc", "def")
    assert factor_set[0] == 1
    assert factor_set[1]
    assert member[0] == factor_record["ref"]


def test_catalog_cli_preflight_is_read_only_and_reports_category_paths(tmp_path) -> None:
    legacy = tmp_path / "legacy.sqlite"
    connection = sqlite3.connect(legacy)
    connection.execute(
        "CREATE TABLE account_product_groups ("
        "username TEXT, group_name TEXT, sort_index INTEGER, "
        "payload_json TEXT, updated_at TEXT)"
    )
    connection.execute(
        "INSERT INTO account_product_groups VALUES (?, ?, ?, ?, ?)",
        (
            "alice", "日盘", 0,
            '{"id":"pg-day","paths":["Product/Futures/CNFutures/日盘/_products/AP.CZC"]}',
            "2026-08-04",
        ),
    )
    connection.commit()
    connection.close()

    profile = tmp_path / "profile.json"
    profile.write_text(
        '{"schema_version":1,"release":{"install_root":"%s"}}'
        % (tmp_path / "client"),
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        client_catalog,
        [
            "migration", "preflight", "--username", "alice",
            "--legacy-db", str(legacy), "--release-profile", str(profile),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value["mode"] == "read_only"
    assert value["safe_to_migrate"] is False
    assert value["groups"][0]["migration_status"] == "category_paths_need_snapshot"
    assert not (tmp_path / "client/catalog/catalog.sqlite").exists()


def test_catalog_cli_lists_owner_scoped_bindings_and_set_members(tmp_path) -> None:
    store = LocalCatalogStore(tmp_path / "client")
    factor_record = _factor_record()
    store.upsert_factor(factor_record)
    store.upsert_group({
        "group_ref": "group:cn",
        "owner_ref": "profile:maxa",
        "name": "中国期货",
    })
    store.replace_group_subjects(
        "group:cn",
        [{"subject_kind": "factor", "subject_ref": factor_record["ref"]}],
    )
    factor_set_record = _factor_set_record(factor_record)
    store.upsert_factor_set(factor_set_record)

    profile = tmp_path / "profile.json"
    profile.write_text(
        '{"schema_version":1,"release":{"install_root":"%s"}}'
        % (tmp_path / "client"),
        encoding="utf-8",
    )
    runner = CliRunner()
    groups = runner.invoke(
        client_catalog,
        ["group", "list", "--owner-ref", "profile:maxa",
         "--release-profile", str(profile), "--json"],
    )
    subjects = runner.invoke(
        client_catalog,
        ["group", "subjects", "group:cn", "--release-profile", str(profile),
         "--json"],
    )
    sets = runner.invoke(
        client_catalog,
        ["factor-set", "list", "--owner-ref", "profile:maxa",
         "--release-profile", str(profile), "--json"],
    )

    assert groups.exit_code == 0, groups.output
    assert subjects.exit_code == 0, subjects.output
    assert sets.exit_code == 0, sets.output
    assert json.loads(groups.output)[0]["group_ref"] == "group:cn"
    assert json.loads(subjects.output)[0]["subject_ref"] == factor_record["ref"]
    listed_set = json.loads(sets.output)[0]
    assert [member["ref"] for member in listed_set["identity"]["members"]] == [
        factor_record["ref"],
    ]
