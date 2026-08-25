from __future__ import annotations

import pytest

from tools.cli.release.research_reporting.references.factor_formula import (
    build_factor_family_reference,
    build_factor_reference,
    parse_factor_family_reference,
    parse_factor_reference,
    verify_factor_family_reference,
    verify_factor_reference,
)

FACTOR_IDENTITY = {
    "owner_ref": "profile:maxa",
    "family_alias": "Momentum",
    "factor_alias": "Momentum:0",
    "family_formula_fingerprint": "a" * 64,
    "self_formula_fingerprint": "b" * 64,
}


def test_factor_reference_is_fixed_length_and_verifies_frozen_identity() -> None:
    value = build_factor_reference(**FACTOR_IDENTITY)

    assert len(value) == len("factor:v2:") + 43
    assert parse_factor_reference(value) == {
        "identity_digest": value.rsplit(":", 1)[-1],
    }
    assert verify_factor_reference(value, **FACTOR_IDENTITY) == FACTOR_IDENTITY
    assert "Momentum" not in value


def test_factor_reference_rejects_mismatched_frozen_identity() -> None:
    value = build_factor_reference(**FACTOR_IDENTITY)
    changed = {**FACTOR_IDENTITY, "factor_alias": "Momentum:1"}

    with pytest.raises(ValueError, match="does not match"):
        verify_factor_reference(value, **changed)


def test_factor_family_reference_is_fixed_length_and_verifiable() -> None:
    identity = {
        "owner_ref": "public",
        "family_alias": "Momentum",
        "family_formula_fingerprint": "c" * 64,
    }
    value = build_factor_family_reference(**identity)

    assert len(value) == len("factor-family:v2:") + 43
    assert parse_factor_family_reference(value) == {
        "identity_digest": value.rsplit(":", 1)[-1],
    }
    assert verify_factor_family_reference(value, **identity) == identity


def test_legacy_or_expanded_factor_reference_is_rejected() -> None:
    with pytest.raises(ValueError, match="v2"):
        parse_factor_reference(
            "factor:v1:profile-maxa:path:alias:" + "a" * 40 + ":" + "b" * 40
        )
    with pytest.raises(ValueError, match="identity_digest"):
        parse_factor_reference("factor:v2:owner:family:factor:" + "a" * 64)
