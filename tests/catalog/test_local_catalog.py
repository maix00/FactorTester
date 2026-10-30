from __future__ import annotations

import json

import pytest

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
