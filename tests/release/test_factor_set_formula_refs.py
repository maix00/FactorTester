from __future__ import annotations

import pytest

from tools.cli.release.research_reporting.references.factor_formula import (
    build_factor_reference,
)
from tools.cli.release.research_reporting.references.factor_set_formula import (
    build_factor_set_reference,
    parse_factor_set_reference,
    verify_factor_set_reference,
)


def _factor(alias: str, fingerprint: str) -> str:
    return build_factor_reference(
        owner_ref="profile:maxa",
        family_alias=alias.split("|", 1)[0],
        factor_alias=alias,
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint=fingerprint * 64,
    )


def test_factor_set_identity_is_independent_of_member_order() -> None:
    first = _factor("Momentum|N:20d", "b")
    second = _factor("Trend|N:5d", "c")

    left = build_factor_set_reference(
        owner_ref="profile:maxa",
        set_id="momentum",
        member_refs=[first, second],
    )
    right = build_factor_set_reference(
        owner_ref="profile:maxa",
        set_id="momentum",
        member_refs=[second, first],
    )

    assert left == right
    assert len(left) == len("factor-set:v2:") + 43
    assert parse_factor_set_reference(left) == {
        "identity_digest": left.rsplit(":", 1)[-1],
    }
    frozen = verify_factor_set_reference(
        left,
        owner_ref="profile:maxa",
        set_id="momentum",
        member_refs=[second, first],
    )
    assert frozen["member_refs"] == sorted([first, second])
    assert len(frozen["member_fingerprint"]) == 64


def test_factor_set_rejects_legacy_or_duplicate_members() -> None:
    factor = _factor("Momentum|N:20d", "b")
    with pytest.raises(ValueError, match="unique"):
        build_factor_set_reference(
            owner_ref="profile:maxa", set_id="momentum",
            member_refs=[factor, factor],
        )
    with pytest.raises(ValueError, match="factor:v2"):
        build_factor_set_reference(
            owner_ref="profile:maxa", set_id="momentum",
            member_refs=["factor:v1:legacy"],
        )
