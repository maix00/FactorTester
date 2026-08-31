"""Research configurations persist one canonical frozen factor collection."""

from __future__ import annotations

import pytest

from server.services.research_configurations import validate_payload
from tools.factors.formula_identity import freeze_factor_identity


def _factor() -> dict:
    return freeze_factor_identity(
        owner_ref="alice",
        family_alias="Momentum",
        factor_alias="Momentum|N:20d",
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint="b" * 64,
        params={"N": "20d"},
    )


def _payload(factors: list[dict]) -> dict:
    return {
        "schema_version": 3,
        "shared": {"factors": factors},
        "analyses": {},
        "ui": {},
    }


def test_configuration_deduplicates_identical_frozen_factors() -> None:
    assert validate_payload(_payload([_factor(), _factor()]))["shared"][
        "factors"
    ] == [_factor()]


def test_configuration_rejects_same_ref_with_different_record() -> None:
    conflicting = _factor()
    conflicting["identity"]["params"] = {"N": "21d"}

    with pytest.raises(ValueError, match="different frozen records"):
        validate_payload(_payload([_factor(), conflicting]))


def test_configuration_rejects_flat_or_legacy_factor_projection() -> None:
    with pytest.raises(ValueError, match="ref must be non-empty"):
        validate_payload(_payload([{
            "factor_ref": "factor:v1:legacy",
            "alias": "Momentum|N:20d",
        }]))
