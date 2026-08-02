from server.services.research_evidence_scope import validate_applicability


def test_evidence_scope_accepts_frozen_factor_set_subject() -> None:
    target = (
        "factor-set:v1:profile-maxa:cGF0aA:aWQ:"
        + "a" * 40 + ":" + "b" * 40
    )
    assert validate_applicability({"factor_refs": [target]}) == {
        "factor_refs": [target]
    }
