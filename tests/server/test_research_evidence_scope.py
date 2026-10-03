import pytest

from server.services.research_evidence_scope import (
    applicability_schema,
    check_identity_scope,
    validate_applicability,
)
from tools.factors.factor_set_identity import freeze_factor_set_identity
from tools.factors.formula_identity import freeze_factor_identity


FACTOR = freeze_factor_identity(
    owner_ref="public",
    family_alias="MmRateOfChg",
    factor_alias="MmRateOfChg|N:20d",
    family_formula_fingerprint="a" * 64,
    self_formula_fingerprint="b" * 64,
    params={"N": "20d"},
)


def test_evidence_scope_accepts_frozen_factor_set_subject() -> None:
    target = freeze_factor_set_identity(
        owner_ref="profile:maxa", set_id="momentum", alias="Momentum",
        members=[FACTOR],
    )["ref"]
    assert validate_applicability({"factor_refs": [target]}) == {
        "factor_refs": [target]
    }


def test_evidence_scope_carries_complete_factor_subject_for_display() -> None:
    assert validate_applicability({
        "factor_refs": [FACTOR["ref"]],
        "factor_subjects": [FACTOR],
    }) == {
        "factor_refs": [FACTOR["ref"]],
        "factor_subjects": [FACTOR],
    }


def test_evidence_scope_accepts_one_sided_time_window() -> None:
    assert validate_applicability({
        "product_scope_ref": "product-group:day",
        "time_window": {"start": "2025-01-01"},
    }) == {
        "product_scope_ref": "product-group:day",
        "time_window": {"start": "2025-01-01"},
    }


def test_applicability_schema_reuses_registered_test_controls() -> None:
    fields = {item["name"]: item for item in applicability_schema()["fields"]}
    assert fields["factor_refs"]["registration"] == "factor_execution"
    assert fields["product_scope_ref"]["registration"] == (
        "product_or_group_selection"
    )
    assert fields["product_scope_ref"]["reuses"] == [
        "product_library_product", "product_path_selection",
    ]
    assert fields["contract_hash"]["exposed"] is False


def test_sample_use_hash_can_scope_reusable_evidence() -> None:
    digest = "c" * 64
    scope = validate_applicability({
        "product_refs": ["product:AP.CZC"],
        "sample_use_hash": digest,
    })
    check_identity_scope(
        {"identity_refs": {"sample_use_hash": digest}},
        scope,
    )
    with pytest.raises(ValueError, match="does not match"):
        check_identity_scope(
            {"identity_refs": {"sample_use_hash": "d" * 64}},
            scope,
        )
