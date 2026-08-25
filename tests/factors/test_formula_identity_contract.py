"""Public contract for formula-addressed factor business identities."""

from __future__ import annotations

import pytest

from tools.data.types import UniqueNameObject
from tools.data.types.object_choices import frozen_object_choice
from tools.data.types.object_identity import unique_frozen_identities
from tools.factors.expr import ConstExpr
from tools.factors.factor_set import FactorSet
from tools.factors.factor_set_identity import freeze_factor_set_identity
from tools.factors.FactorFamily import FactorFamily
from tools.factors.Factors import Factor
from tools.factors.formula_identity import (
    freeze_factor_family_identity,
    freeze_factor_identity,
    require_frozen_factor,
)


def test_business_code_receives_one_verified_frozen_factor_record() -> None:
    frozen = freeze_factor_identity(
        owner_ref="user:alice",
        family_alias="Momentum",
        factor_alias="Momentum|N:20d",
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint="b" * 64,
        params={"N": "20d"},
    )

    assert require_frozen_factor(frozen) == frozen
    assert frozen["ref"].startswith("factor:v2:")
    assert frozen["identity"]["family_ref"].startswith("factor-family:v2:")
    assert frozen["alias"] == "Momentum|N:20d"


def test_unique_name_object_interns_by_frozen_object_ref_not_alias() -> None:
    first_identity = freeze_factor_identity(
        owner_ref="user:alice",
        family_alias="Momentum",
        factor_alias="Momentum|N:20d",
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint="b" * 64,
        params={"N": "20d"},
    )
    changed_formula = freeze_factor_identity(
        owner_ref="user:alice",
        family_alias="Momentum",
        factor_alias="Momentum|N:20d",
        family_formula_fingerprint="c" * 64,
        self_formula_fingerprint="d" * 64,
        params={"N": "20d"},
    )

    first = Factor(ConstExpr(1), frozen_identity=first_identity)
    repeated = Factor(ConstExpr(1), frozen_identity=first_identity)
    changed = Factor(ConstExpr(1), frozen_identity=changed_formula)

    assert first is repeated
    assert first is not changed
    assert first.name == first_identity["ref"]
    assert first.alias == "Momentum|N:20d"


def test_runtime_factor_pool_does_not_reuse_same_alias_with_changed_formula() -> None:
    first = Factor(ConstExpr(101), alias="ProfileScreen|N:20d", owner_ref="alice")
    repeated = Factor(ConstExpr(101), alias="ProfileScreen|N:20d", owner_ref="alice")
    changed = Factor(ConstExpr(202), alias="ProfileScreen|N:20d", owner_ref="alice")

    assert first is repeated
    assert first is not changed
    assert first._source_expr.semantic_fingerprint() != (
        changed._source_expr.semantic_fingerprint()
    )


def test_factor_set_is_a_unique_object_with_complete_frozen_members() -> None:
    member = freeze_factor_identity(
        owner_ref="user:alice",
        family_alias="Momentum",
        factor_alias="Momentum|N:20d",
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint="b" * 64,
        params={"N": "20d"},
    )
    frozen = freeze_factor_set_identity(
        owner_ref="user:alice",
        set_id="momentum",
        alias="动量因子集合",
        members=[member],
    )

    factor_set = FactorSet(frozen_identity=frozen)

    assert factor_set.name == frozen["ref"]
    assert factor_set.alias == "动量因子集合"
    assert factor_set.members == (member,)
    assert factor_set.serialize() == frozen
    assert UniqueNameObject.deserialize(frozen) is factor_set


def test_factor_family_uses_its_formula_ref_as_unique_name() -> None:
    frozen = freeze_factor_family_identity(
        owner_ref="user:alice",
        family_alias="Momentum",
        family_formula_fingerprint="a" * 64,
    )

    family = FactorFamily(alias="Momentum", frozen_identity=frozen)

    assert family.name == frozen["ref"]
    assert family.alias == frozen["alias"]


def test_factor_deserialization_hydrates_runtime_expression_through_resolver() -> None:
    frozen = freeze_factor_identity(
        owner_ref="user:alice",
        family_alias="Momentum",
        factor_alias="Momentum|N:60d",
        family_formula_fingerprint="e" * 64,
        self_formula_fingerprint="f" * 64,
        params={"N": "60d"},
    )

    factor = UniqueNameObject.deserialize(
        frozen,
        resolver=lambda identity: {"expr": ConstExpr(2), "family": None},
    )

    assert isinstance(factor, Factor)
    assert factor.name == frozen["ref"]


def test_frontend_choice_uses_alias_but_carries_complete_frozen_record() -> None:
    frozen = freeze_factor_identity(
        owner_ref="user:alice",
        family_alias="Momentum",
        factor_alias="Momentum|N:60d",
        family_formula_fingerprint="e" * 64,
        self_formula_fingerprint="f" * 64,
        params={"N": "60d"},
    )

    assert frozen_object_choice(frozen) == {
        "value": frozen["ref"],
        "label": "Momentum|N:60d",
        "record": frozen,
    }


def test_frozen_identity_boundary_deduplicates_by_ref_and_rejects_conflicts() -> None:
    frozen = freeze_factor_identity(
        owner_ref="user:alice",
        family_alias="Momentum",
        factor_alias="Momentum|N:20d",
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint="b" * 64,
        params={"N": "20d"},
    )

    assert unique_frozen_identities([frozen, frozen]) == [frozen]
    conflicting = {**frozen, "identity": {**frozen["identity"], "params": {}}}
    with pytest.raises(ValueError, match="different frozen records"):
        unique_frozen_identities([frozen, conflicting])
