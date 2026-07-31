import pytest

from tools.factors.subject_refs import factor_subject_kind
from tools.cli.release.research_obligations.scope_revalidation import (
    normalize_scope,
)


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        (
            "factor:v1:profile-maxa:cGF0aA:aWQ:"
            + "a" * 40 + ":" + "b" * 40,
            "factor",
        ),
        (
            "factor-family:v1:profile-maxa:cGF0aA:aWQ:"
            + "a" * 40 + ":" + "b" * 40,
            "factor_family",
        ),
        (
            "factor-set:v1:profile-maxa:cGF0aA:aWQ:"
            + "a" * 40 + ":" + "b" * 40,
            "factor_set",
        ),
        ("factor-expr:F|N:20d@sha256:" + "c" * 64, "factor_expr_execution"),
    ],
)
def test_factor_subject_accepts_only_frozen_identities(value, kind):
    assert factor_subject_kind(value) == kind


@pytest.mark.parametrize(
    "value",
    ["factor-set:profile-maxa:momentum", "factor:anything", "factor-family:F"],
)
def test_factor_subject_rejects_lookup_and_unversioned_refs(value):
    with pytest.raises(ValueError, match="frozen"):
        factor_subject_kind(value)


def test_scope_normalization_rejects_instead_of_silently_dropping_factor() -> None:
    with pytest.raises(ValueError, match="factor subject"):
        normalize_scope({"factor_refs": ["factor-set:profile-maxa:momentum"]})
