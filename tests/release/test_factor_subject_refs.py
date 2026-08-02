import pytest

from tools.cli.factor_subject_refs import factor_subject_kind
from tools.cli.commands.research_graph_factor_subjects import (
    attach_transition_factor_subjects,
    factor_subject_refs_from_report,
)
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


def test_current_report_requirement_selects_its_typed_factor_binding() -> None:
    selected = (
        "factor:v1:profile-maxa:cGF0aA:c2VsZWN0ZWQ:"
        + "a" * 40 + ":" + "b" * 40
    )
    unrelated = (
        "factor:v1:profile-maxa:cGF0aA:dW5yZWxhdGVk:"
        + "c" * 40 + ":" + "d" * 40
    )
    snapshot = {
        "components": [
            {"component_id": "chapter", "parent_id": "root"},
            {"component_id": "selected", "parent_id": "chapter"},
            {"component_id": "unrelated", "parent_id": "chapter"},
            {"component_id": "other-chapter", "parent_id": "root"},
        ],
        "bindings": [
            {
                "component_id": "selected",
                "kind": "report_requirement",
                "target_ref": "report.node.factor_semantics.action",
            },
            {
                "component_id": "selected",
                "kind": "factor",
                "target_ref": selected,
            },
            {
                "component_id": "unrelated",
                "kind": "factor",
                "target_ref": unrelated,
            },
            {
                "component_id": "other-chapter",
                "kind": "report_requirement",
                "target_ref": "report.node.factor_semantics.action",
            },
            {
                "component_id": "other-chapter",
                "kind": "factor",
                "target_ref": unrelated,
            },
        ],
    }

    assert factor_subject_refs_from_report(
        snapshot,
        chapter_component_id="chapter",
        requirement_ids={"report.node.factor_semantics.action"},
    ) == [selected]

    evidence: dict = {}
    attach_transition_factor_subjects(
        evidence,
        action_contract={
            "factor_subject_source": "current_report_requirement_bindings",
        },
        snapshot=snapshot,
        chapter_component_id="chapter",
        requirement_ids={"report.node.factor_semantics.action"},
    )
    assert evidence["factor_subject_refs"] == [selected]
