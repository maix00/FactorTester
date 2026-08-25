import pytest

from server.services.factor_subject_descriptors import (
    assert_factor_sets_match_run,
    compact_factor_subject_descriptors,
    factor_refs_by_alias,
    validate_factor_subject_descriptors,
)
from tools.factors.factor_set_identity import freeze_factor_set_identity
from tools.factors.formula_identity import (
    freeze_factor_identity,
)


def _member(alias: str = "F|N:20d") -> dict:
    return freeze_factor_identity(
        owner_ref="profile:maxa",
        family_alias="F",
        factor_alias=alias,
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint="b" * 64,
        params={"N": "20d"},
    )


def _descriptor(alias: str = "F|N:20d") -> dict:
    member = _member(alias)
    manifest = freeze_factor_set_identity(
        owner_ref="profile:maxa",
        set_id="momentum",
        alias="动量集合",
        members=[member],
    )
    return {
        "target_ref": manifest["ref"],
        "manifest": manifest,
    }


def test_descriptor_binds_set_and_every_member_formula_identity() -> None:
    values = validate_factor_subject_descriptors([_descriptor()])
    assert values[0]["member_count"] == 1
    assert_factor_sets_match_run(
        values,
        factor_refs={_member()["ref"]},
    )
    assert compact_factor_subject_descriptors(values) == [{
        "target_ref": _descriptor()["target_ref"],
        "member_fingerprint": values[0]["member_fingerprint"],
        "member_count": 1,
        "authority": "formula_manifest",
    }]


def test_descriptor_rejects_factor_set_not_executed_by_run() -> None:
    values = validate_factor_subject_descriptors([_descriptor()])
    with pytest.raises(ValueError, match="exactly match"):
        assert_factor_sets_match_run(
            values,
            factor_refs={_member("F|N:10d")["ref"]},
        )


def test_factor_ref_bindings_preserve_each_member_identity() -> None:
    values = validate_factor_subject_descriptors([_descriptor("F|N:20d|X:foo")])
    bindings = factor_refs_by_alias(values)
    assert list(bindings) == ["F|N:20d|X:foo"]
    assert bindings["F|N:20d|X:foo"].startswith("factor:v2:")


def test_descriptor_rejects_member_identity_tampering() -> None:
    descriptor = _descriptor()
    descriptor["manifest"]["identity"]["members"][0]["alias"] = "F|N:5d"
    with pytest.raises(ValueError, match="does not match"):
        validate_factor_subject_descriptors([descriptor])
