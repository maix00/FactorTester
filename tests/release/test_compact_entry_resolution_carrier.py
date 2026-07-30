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
