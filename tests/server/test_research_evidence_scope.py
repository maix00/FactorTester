import pytest

from server.services.research_evidence_scope import validate_applicability


def test_evidence_scope_rejects_stable_factor_set_lookup_ref() -> None:
    with pytest.raises(ValueError, match="non-frozen"):
        validate_applicability({
            "factor_refs": ["factor-set:profile-maxa:momentum"],
        })


def test_evidence_scope_accepts_frozen_factor_set_subject() -> None:
    target = (
        "factor-set:v1:profile-maxa:cGF0aA:aWQ:"
        + "a" * 40 + ":" + "b" * 40
    )
    assert validate_applicability({"factor_refs": [target]}) == {
        "factor_refs": [target]
    }
