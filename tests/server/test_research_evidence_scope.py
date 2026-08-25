from server.services.research_evidence_scope import validate_applicability
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
