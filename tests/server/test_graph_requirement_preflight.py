"""Deterministic Graph-upgrade requirement delta semantics."""

from copy import deepcopy

from server.services.research_graph.branch.requirement_preflight import (
    assess_requirement_continuation,
)


def _graph(*, revision: int = 1, question: str = "原问题") -> dict:
    return {
        "nodes": [{
            "node_id": "factor_semantics",
            "entry_requirement_refs": ["factor_semantics.expression_identity"],
        }],
        "requirement_catalog": {
            "requirements": [{
                "requirement_id": "factor_semantics.expression_identity",
                "revision": revision,
                "question_zh": question,
            }],
        },
    }


def test_wording_change_is_audit_metadata_not_reentry_work() -> None:
    source = _graph()
    target = _graph(question="改进后的中文说明")

    delta = assess_requirement_continuation(
        source_graph=source,
        target_graph=target,
        target_node="factor_semantics",
    )

    assert delta["entry_revised_ids"] == []
    assert delta["entry_metadata_changed_ids"] == [
        "factor_semantics.expression_identity"
    ]
    assert delta["assessment_required_ids"] == []


def test_explicit_revision_reopens_only_the_current_requirement() -> None:
    source = _graph()
    target = _graph(revision=2, question="新增了语义判断要求")
    target["requirement_catalog"]["requirements"].append({
        "requirement_id": "data.required_fields",
        "revision": 1,
        "question_zh": "字段是否存在？",
    })
    other_node = deepcopy(target["nodes"][0])
    other_node.update({
        "node_id": "data_contract",
        "entry_requirement_refs": ["data.required_fields"],
    })
    target["nodes"].append(other_node)

    delta = assess_requirement_continuation(
        source_graph=source,
        target_graph=target,
        target_node="factor_semantics",
    )

    assert delta["catalog_added_count"] == 1
    assert delta["entry_added_ids"] == []
    assert delta["entry_revised_ids"] == [
        "factor_semantics.expression_identity"
    ]
    assert delta["assessment_required_ids"] == delta["entry_revised_ids"]
