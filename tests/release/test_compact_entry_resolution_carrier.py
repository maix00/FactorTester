from __future__ import annotations

from copy import deepcopy

from tools.cli.release.research_reporting.publisher.carrier import (
    canonical_carrier,
)
from tests.release.report_tree_fixtures import carrier


def test_canonical_carrier_accepts_compact_entry_resolution_rows() -> None:
    value = deepcopy(carrier())
    value["latest_transition"]["entry_resolution"] = {
        "reason": "node_entry",
        "assessed_requirement_ids": [],
        "reused_requirement_ids": [],
        "reference_only_requirement_ids": [],
        "unresolved_requirement_ids": [
            "other.unclassified_material_question",
        ],
        "items": [{
            "requirement_id": "other.unclassified_material_question",
            "change_kind": "unchanged",
            "resolution_status": "unresolved",
        }],
        "resume_node": "hypothesis_preregistration",
    }

    result = canonical_carrier(value)

    assert result["latest_transition"]["entry_resolution"]["items"] == [{
        "requirement_id": "other.unclassified_material_question",
        "change_kind": "unchanged",
        "resolution_status": "unresolved",
    }]


def test_canonical_carrier_accepts_titled_obligation_presentations() -> None:
    value = deepcopy(carrier())
    value["latest_transition"]["obligation_presentations"] = [{
        "obligation_ref": "obligation:data-contract",
        "title_zh": "数据契约",
        "question_summary": "数据是否足以支持预注册检验？",
    }]

    result = canonical_carrier(value)

    assert result["latest_transition"]["obligation_presentations"] == [{
        "obligation_ref": "obligation:data-contract",
        "title_zh": "数据契约",
        "question_summary": "数据是否足以支持预注册检验？",
    }]


def test_canonical_carrier_accepts_entry_resolution_union_over_16_rows() -> None:
    value = deepcopy(carrier())
    assessed_ids = [f"data.requirement_{index}" for index in range(7)]
    unresolved_ids = [
        f"factor_semantics.requirement_{index}" for index in range(11)
    ]
    value["latest_transition"]["entry_resolution"] = {
        "reason": "node_entry",
        "assessed_requirement_ids": assessed_ids,
        "reused_requirement_ids": [],
        "reference_only_requirement_ids": [],
        "unresolved_requirement_ids": unresolved_ids,
        "items": [
            {
                "requirement_id": requirement_id,
                "change_kind": "unchanged",
                "resolution_status": status,
            }
            for status, identifiers in (
                ("assessed_limited", assessed_ids),
                ("unresolved", unresolved_ids),
            )
            for requirement_id in identifiers
        ],
        "resume_node": "factor_semantics",
    }

    result = canonical_carrier(value)

    assert len(result["latest_transition"]["entry_resolution"]["items"]) == 18
