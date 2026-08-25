"""Frozen factor formula identities are the sole RunSpec execution source."""

from __future__ import annotations

from copy import deepcopy

import pytest

from server.services import factor_revisions
from tools.factors.formula_identity import freeze_factor_identity


def _factor(*, self_fingerprint: str = "b" * 64) -> dict:
    return freeze_factor_identity(
        owner_ref="alice",
        family_alias="ConditionalAlpha",
        factor_alias="ConditionalAlpha|AUX:[Trend|N:20d]",
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint=self_fingerprint,
        params={"N": "20d"},
    )


def _configuration(*, factors: list[dict] | None = None) -> dict:
    return {
        "configuration_id": "configuration-1",
        "revision": 3,
        "fingerprint": "f" * 64,
        "payload": {
            "schema_version": 2,
            "shared": {
                "factor_families": [{"alias": "ConditionalAlpha"}],
                "factors": deepcopy(factors or [_factor()]),
            },
            "analyses": {"ic": {}},
            "ui": {},
        },
    }


def _definition(*, self_fingerprint: str = "b" * 64) -> dict:
    return {
        "canonical_family_ref": "alice:ConditionalAlpha",
        "factor_owner_ref": "alice",
        "factor_family_alias": "ConditionalAlpha",
        "family_formula_fingerprint": "a" * 64,
        "resolved_factors": [{
            "factor_alias": "ConditionalAlpha|AUX:[Trend|N:20d]",
            "self_formula_fingerprint": self_fingerprint,
            "params": {"N": "20d"},
            "column_refs": [],
        }],
    }


def test_freeze_keeps_one_canonical_factor_source_and_deduplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        factor_revisions,
        "_load_revision_definition",
        lambda **_kwargs: _definition(),
    )
    frozen = factor_revisions.freeze_factor_revisions(
        _configuration(factors=[_factor(), _factor()]), owner="alice",
    )

    shared = frozen["payload"]["shared"]
    assert shared["factors"] == [_factor()]
    assert "factor_revision_manifests" not in shared
    assert "factor_families" not in shared


def test_execution_validates_the_same_frozen_factor_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _definition()
    monkeypatch.setattr(
        factor_revisions,
        "_load_revision_definition",
        lambda **_kwargs: deepcopy(current),
    )
    frozen = factor_revisions.freeze_factor_revisions(
        _configuration(), owner="alice",
    )
    run_spec = {
        "run_spec_version": 3,
        "configuration": frozen["payload"],
    }

    factor_revisions.assert_run_spec_factor_revisions_current(
        run_spec, owner="alice",
    )
    current["resolved_factors"][0]["params"] = {"N": "21d"}
    with pytest.raises(ValueError, match="factor formula changed"):
        factor_revisions.assert_run_spec_factor_revisions_current(
            run_spec, owner="alice",
        )
    current["resolved_factors"][0]["params"] = {"N": "20d"}
    current["resolved_factors"][0]["self_formula_fingerprint"] = "c" * 64

    with pytest.raises(ValueError, match="factor formula changed"):
        factor_revisions.assert_run_spec_factor_revisions_current(
            run_spec, owner="alice",
        )


def test_legacy_or_incomplete_factor_identity_is_rejected() -> None:
    legacy = _configuration()
    legacy["payload"]["shared"]["factors"] = [{
        "factor_ref": "factor:v1:legacy",
        "alias": "ConditionalAlpha|AUX:[Trend|N:20d]",
    }]

    with pytest.raises(ValueError, match="ref must be non-empty"):
        factor_revisions.freeze_factor_revisions(legacy, owner="alice")


def test_same_ref_with_conflicting_record_is_rejected() -> None:
    conflicting = _factor()
    conflicting["identity"]["params"] = {"N": "21d"}

    with pytest.raises(ValueError, match="different frozen records"):
        factor_revisions.freeze_factor_revisions(
            _configuration(factors=[_factor(), conflicting]), owner="alice",
        )
