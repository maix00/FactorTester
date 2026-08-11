from __future__ import annotations

from tests.public_factor_source import load_public_factor_class


MmRateOfChg = load_public_factor_class("MmRateOfChg")


def _ref(kind: str, identity: str) -> str:
    return (
        f"{kind}:v1:profile-maxa:cGF0aA:{identity}:"
        + "a" * 40 + ":" + "b" * 40
    )


def test_frozen_runtime_objects_use_refs_without_changing_aliases() -> None:
    family_ref = _ref("factor-family", "TW1SYXRlT2ZDaGc")
    factor_ref = _ref("factor", "YWxpYXM")
    family = MmRateOfChg(
        family_ref=family_ref,
        owner_ref="profile:maxa",
    )
    expected_alias = family.get_alias(P="CA", N="20d", **{"$F": "1d"})

    factor = family.get_factor(
        N="20d",
        **{
            "$F": "1d",
            "factor_refs": {expected_alias: factor_ref},
        },
    )

    assert family.name == family_ref
    assert family.family_ref == family_ref
    assert family.owner_ref == "profile:maxa"
    assert family.alias == "MmRateOfChg"
    assert factor.name == factor_ref
    assert factor.factor_ref == factor_ref
    assert factor.owner_ref == "profile:maxa"
    assert factor.alias == expected_alias


def test_unfrozen_public_runtime_name_does_not_emit_common_owner() -> None:
    family = MmRateOfChg()
    factor = family.get_factor(N="10d", **{"$F": "5d"})

    assert family.owner_ref == "public"
    assert "$COMMON" not in family.name
    assert factor.owner_ref == "public"
    assert "$COMMON" not in factor.name
