import pytest

from tools.cli.factor_subject_refs import (
    factor_reference_kind,
    factor_subject_kind,
    split_owner_qualified_factor_family,
)
from tools.cli.commands.research_graph_factor_subjects import (
    attach_transition_factor_subjects,
    factor_subject_refs_from_report,
)


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        (
            "factor:v2:" + "a" * 43,
            "factor",
        ),
        (
            "factor-set:v2:" + "b" * 43,
            "factor_set",
        ),
    ],
)
def test_factor_subject_accepts_only_frozen_identities(value, kind):
    assert factor_subject_kind(value) == kind


def test_factor_family_is_a_navigation_reference_not_a_subject() -> None:
    value = "factor-family:v2:" + "c" * 43

    assert factor_reference_kind(value) == "factor_family"
    with pytest.raises(ValueError, match="navigation-only"):
        factor_subject_kind(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("MmRateOfChg", (None, "MmRateOfChg")),
        ("18717974771:MmRateOfChg", ("18717974771", "MmRateOfChg")),
        ("profile:maxa:MmRateOfChg", ("profile:maxa", "MmRateOfChg")),
        ("user:18717974771:MmRateOfChg", ("user:18717974771", "MmRateOfChg")),
        ("public:MmRateOfChg", ("public", "MmRateOfChg")),
        ("$COMMON:MmRateOfChg", ("public", "MmRateOfChg")),
    ],
)
def test_owner_qualified_family_preserves_owner_namespace(value, expected) -> None:
    assert split_owner_qualified_factor_family(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "profile:maxa",
        "user:18717974771",
        "public:",
        "factor:v1:profile-maxa:cGF0aA:aWQ:" + "a" * 40 + ":" + "b" * 40,
    ],
)
def test_owner_reference_or_typed_ref_is_not_a_family_selector(value) -> None:
    with pytest.raises(ValueError):
        split_owner_qualified_factor_family(value)

def test_current_report_requirement_selects_its_typed_factor_binding() -> None:
    selected = "factor:v2:" + "d" * 43
    unrelated = "factor:v2:" + "e" * 43
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
