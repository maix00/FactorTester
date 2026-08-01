from __future__ import annotations

import hashlib
import json

from tools.cli.commands.research_report_graph_guard import (
    _validate_historical_review,
)


def test_historical_review_allows_only_title_preserving_section_wrap() -> None:
    components = [
        {
            "component_id": "chapter", "kind": "chapter",
            "parent_id": None, "title": "数据契约", "body": "",
            "content": None, "display_kind": "",
        },
        {
            "component_id": "finding", "kind": "entry",
            "parent_id": "chapter", "title": "数据范围", "body": "正文",
            "content": None, "display_kind": "",
        },
    ]
    operations = [
        {
            "op": "add", "component_id": "finding-section",
            "kind": "section", "parent_id": "chapter",
            "after_component_id": None, "title": "数据范围", "body": "",
            "content": None, "display_kind": "", "bindings": [],
        },
        {
            "op": "replace", "component_id": "finding", "title": "",
            "body": "正文", "content": None, "display_kind": "",
            "bindings": [],
        },
        {
            "op": "move", "component_id": "finding",
            "parent_id": "finding-section", "after_component_id": None,
        },
        {
            "op": "move", "component_id": "finding-section",
            "parent_id": "chapter", "after_component_id": None,
        },
    ]
    identities = sorted(item["component_id"] for item in components)
    review = {
        "schema_version": 1,
        "kind": "historical_source_correction",
        "reviewed_component_count": len(identities),
        "reviewed_component_digest": hashlib.sha256(json.dumps(
            identities, ensure_ascii=False, separators=(",", ":"),
        ).encode()).hexdigest(),
        "components": [
            {"component_id": item["component_id"], "reason": "修复小节层级"}
            for item in operations
        ],
    }

    _validate_historical_review(
        {"components": components, "bindings": []},
        operations=operations,
        review=review,
    )
