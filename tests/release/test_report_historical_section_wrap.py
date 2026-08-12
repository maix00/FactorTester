from __future__ import annotations

import hashlib
import json

from tools.cli.commands.research_report_graph_guard import (
    _validate_historical_review,
)
from tools.cli.release.research_reporting.authoring.tree_replacement import (
    retained_attached_bindings,
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


def test_historical_wrap_moves_display_semantics_to_section() -> None:
    components = [{
        "component_id": "coverage", "kind": "table",
        "parent_id": "special", "title": "义务要求覆盖", "body": "",
        "content": {"columns": [], "rows": []},
        "display_kind": "obligation_requirement_coverage",
    }]
    operations = [
        {
            "op": "add", "component_id": "coverage-section",
            "kind": "section", "parent_id": "special",
            "after_component_id": None, "title": "义务要求覆盖",
            "body": "", "content": None,
            "display_kind": "obligation_requirement_coverage",
        },
        {
            "op": "replace", "component_id": "coverage", "title": "",
            "body": "", "content": {"columns": [], "rows": []},
            "display_kind": "",
        },
        {
            "op": "move", "component_id": "coverage-section",
            "parent_id": "special", "after_component_id": None,
        },
        {
            "op": "move", "component_id": "coverage",
            "parent_id": "coverage-section", "after_component_id": None,
        },
    ]
    identities = ["coverage"]
    review = {
        "schema_version": 1,
        "kind": "historical_source_correction",
        "reviewed_component_count": 1,
        "reviewed_component_digest": hashlib.sha256(json.dumps(
            identities, ensure_ascii=False, separators=(",", ":"),
        ).encode()).hexdigest(),
        "components": [{
            "component_id": item["component_id"],
            "reason": "恢复普通小节",
        } for item in operations],
    }

    _validate_historical_review(
        {"components": components, "bindings": []},
        operations=operations,
        review=review,
    )


def test_historical_review_normalizes_only_same_job_legacy_evidence() -> None:
    job_id = "a" * 32
    components = [{
        "component_id": "result", "kind": "special",
        "parent_id": "chapter", "title": "测试结果",
        "body": (
            "关联：\n- [Job 终态证据](factortester://evidence/"
            f"evidence%3Ajob%3A{job_id})"
        ),
        "content": None, "display_kind": "test_result",
    }]
    operations = [{
        "op": "replace", "component_id": "result", "title": "测试结果",
        "body": f"关联：\n- [测试任务](factortester://job/job%3A{job_id})",
        "content": None, "display_kind": "test_result",
    }]
    review = _review(components, operations)

    _validate_historical_review(
        {"components": components, "bindings": []},
        operations=operations, review=review,
    )


def test_replacement_drops_legacy_fake_job_evidence_binding() -> None:
    kept = retained_attached_bindings([
        {
            "binding_id": "evidence-old-result", "kind": "evidence",
            "target_ref": "evidence:job:" + "a" * 32,
        },
        {
            "binding_id": "run-spec-result", "kind": "run_spec",
            "target_ref": "runspec:sha256:" + "b" * 64,
        },
    ])

    assert [item["binding_id"] for item in kept] == ["run-spec-result"]


def _review(components, operations):
    identities = sorted(item["component_id"] for item in components)
    return {
        "schema_version": 1,
        "kind": "historical_source_correction",
        "reviewed_component_count": len(identities),
        "reviewed_component_digest": hashlib.sha256(json.dumps(
            identities, ensure_ascii=False, separators=(",", ":"),
        ).encode()).hexdigest(),
        "components": [{
            "component_id": item["component_id"], "reason": "修正旧任务引用",
        } for item in operations],
    }
