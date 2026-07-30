from __future__ import annotations

from pathlib import Path

from tools.cli.release.research_reporting.authoring.checkpoint_operations import (
    checkpoint_operations,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    apply_batch,
    ensure_node_chapter,
    initialize_tree,
    load_snapshot,
)
from tools.cli.release.research_reporting.authoring.tree_render import (
    render_tree_markdown,
)
from tools.cli.release.research_reporting.authoring.submission import (
    build_report_submission,
)


def test_checkpoint_operations_preserve_report_content_and_system_links(tmp_path: Path) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(package_root=package, branch_id="main", report_id="report-wp", title="研究报告")
    chapter = ensure_node_chapter(
        package_root=package, branch_id="main", node_id="trial_execution", title="试验执行",
    )
    source = {
        "assets": [{
            "asset_ref": "asset:equity", "media_type": "image/svg+xml",
            "filename": "equity.svg", "caption": "权益曲线", "alt_text": "权益曲线",
        }],
        "sections": [{
            "section_id": "checkpoint-a", "title": "执行结果", "body": "总体结果可读",
            "links": [
                {"link_id": "ev", "kind": "evidence", "target_ref": "evidence:one", "label": "证据"},
                {"link_id": "plan", "kind": "trial_plan", "target_ref": "trial-plan:one", "label": "计划"},
            ],
            "blocks": [
                {"kind": "paragraph", "text": "段落内容", "link_ids": ["ev"]},
                {"kind": "list", "rows": [{"text": "列表内容", "link_ids": ["ev"]}]},
                {"kind": "table", "columns": ["指标", "值"], "rows": [{"cells": ["Sharpe", "1.2"], "link_ids": ["plan"]}]},
                {"kind": "math", "latex": "r_t", "fallback": "收益率", "link_ids": ["ev"]},
                {"kind": "figure", "asset": {"asset_ref": "asset:equity", "caption": "权益曲线"}, "link_ids": ["ev"], "report_binding": {"report_requirement_id": "requirement:equity", "subject_ref": "factor:one", "report_item_ref": "report-item:sha256:" + "a" * 64}},
            ],
        }],
        "gaps": [{"gap_ref": "gap:coverage", "reason": "仍需补充覆盖率"}],
    }
    snapshot = load_snapshot(package_root=package, branch_id="main")
    operations = checkpoint_operations(
        source, parent_id=chapter["component_id"],
        component_exists={item["component_id"] for item in snapshot["components"]}.__contains__,
        binding_exists={item["binding_id"] for item in snapshot["bindings"]}.__contains__,
        asset_exists={item["asset_ref"] for item in snapshot["head"]["assets"]}.__contains__,
    )
    section = next(
        item for item in operations
        if item.get("op") == "add" and item.get("kind") == "section"
    )
    assert section["body"] == "总体结果可读"
    apply_batch(package_root=package, branch_id="main", operations=operations)
    saved = load_snapshot(package_root=package, branch_id="main")
    rendered = render_tree_markdown(saved).decode()
    assert all(value in rendered for value in ("段落内容", "列表内容", "| Sharpe | 1.2 |", "$$\nr_t", "![权益曲线](../../assets/equity.svg)", "仍需补充覆盖率"))
    assert "factortester://evidence/evidence%3Aone" in rendered
    assert "factortester://trial_plan/trial-plan%3Aone" in rendered
    assert "factortester://report_requirement/requirement%3Aequity" in rendered
    assert {item["kind"] for item in saved["bindings"]} >= {"evidence", "trial_plan", "report_requirement"}
    requirement_binding = next(
        item for item in saved["bindings"]
        if item["kind"] == "report_requirement"
    )
    assert requirement_binding["data"]["content_kind"] == "figure"
    submission = build_report_submission(saved)
    assert submission["items"][0]["item_hash"] == "a" * 64

    repeated = checkpoint_operations(
        source, parent_id=chapter["component_id"],
        component_exists={item["component_id"] for item in saved["components"]}.__contains__,
        binding_exists={item["binding_id"] for item in saved["bindings"]}.__contains__,
        asset_exists={item["asset_ref"] for item in saved["head"]["assets"]}.__contains__,
    )
    assert repeated == []


def test_checkpoint_operations_preserve_obligation_changes_as_special_section(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    chapter = ensure_node_chapter(
        package_root=package, branch_id="main", node_id="trial_execution",
        title="试验执行",
    )
    source = {
        "assets": [],
        "sections": [
            {
                "section_id": "result", "title": "试验结果",
                "section_role": "trial_result", "body": "结果正文",
                "links": [], "blocks": [],
            },
            {
                "section_id": "obligation-delta",
                "title": "审计与义务变化",
                "section_role": "obligation_changes", "body": "",
                "links": [{
                    "link_id": "obligation", "kind": "obligation",
                    "target_ref": "obligation:predictive-validity",
                    "label": "预测有效性",
                }],
                "blocks": [{
                    "kind": "table", "columns": ["义务", "原状态", "新状态"],
                    "rows": [{
                        "cells": ["预测有效性", "待处理", "已限定"],
                        "link_ids": ["obligation"],
                    }],
                }],
            },
        ],
        "gaps": [],
    }
    snapshot = load_snapshot(package_root=package, branch_id="main")
    operations = checkpoint_operations(
        source, parent_id=chapter["component_id"],
        component_exists={item["component_id"] for item in snapshot["components"]}.__contains__,
        binding_exists={item["binding_id"] for item in snapshot["bindings"]}.__contains__,
        asset_exists={item["asset_ref"] for item in snapshot["head"]["assets"]}.__contains__,
    )

    additions = [item for item in operations if item.get("op") == "add"]
    result = next(item for item in additions if item["title"] == "试验结果")
    special = next(
        item for item in additions
        if item["title"] == "审计与义务变化"
    )
    assert additions.index(result) < additions.index(special)
    assert result["parent_id"] == chapter["component_id"]
    assert special["parent_id"] == chapter["component_id"]
    assert special["kind"] == "special"
    assert special["display_kind"] == "obligation_changes"
    assert special["bindings"][0]["kind"] == "obligation"


def test_obligation_changes_can_nest_under_one_authored_section(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    chapter = ensure_node_chapter(
        package_root=package, branch_id="main", node_id="trial_execution",
        title="试验执行",
    )
    source = {
        "assets": [],
        "sections": [
            {
                "section_id": "result", "title": "试验结果",
                "section_role": "trial_result", "body": "",
                "links": [], "blocks": [],
            },
            {
                "section_id": "obligation-delta",
                "parent_section_id": "result",
                "title": "该结果引起的义务变化",
                "section_role": "obligation_changes", "body": "",
                "links": [], "blocks": [],
            },
        ],
        "gaps": [],
    }
    snapshot = load_snapshot(package_root=package, branch_id="main")
    operations = checkpoint_operations(
        source, parent_id=chapter["component_id"],
        component_exists={
            item["component_id"] for item in snapshot["components"]
        }.__contains__,
        binding_exists={
            item["binding_id"] for item in snapshot["bindings"]
        }.__contains__,
        asset_exists={
            item["asset_ref"] for item in snapshot["head"]["assets"]
        }.__contains__,
    )

    additions = [item for item in operations if item.get("op") == "add"]
    result = next(item for item in additions if item["title"] == "试验结果")
    obligation = next(
        item for item in additions
        if item["title"] == "该结果引起的义务变化"
    )
    assert obligation["parent_id"] == result["component_id"]
    assert obligation["kind"] == "special"
    assert obligation["display_kind"] == "obligation_changes"


def test_obligation_changes_nest_inside_active_capability_detour(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    chapter = ensure_node_chapter(
        package_root=package, branch_id="main",
        node_id="hypothesis_preregistration", title="假设登记",
    )
    detour_id = "special-capability-episode"
    add_component(
        package_root=package, branch_id="main",
        component_id=detour_id, kind="special",
        title="能力修复过程", parent_id=chapter["component_id"],
        body="", content={}, display_kind="capability_detour",
    )
    source = {
        "assets": [],
        "sections": [
            {
                "section_id": "repair", "title": "修复结果",
                "body": "能力已补齐", "links": [], "blocks": [],
            },
            {
                "section_id": "obligation-delta", "title": "义务变化",
                "section_role": "obligation_changes", "body": "",
                "links": [], "blocks": [],
            },
        ],
        "gaps": [],
    }

    snapshot = load_snapshot(package_root=package, branch_id="main")
    detour = next(
        item for item in snapshot["components"]
        if item["component_id"] == detour_id
    )
    operations = checkpoint_operations(
        source, parent_id=detour["component_id"], parent_kind=detour["kind"],
        component_exists={
            item["component_id"] for item in snapshot["components"]
        }.__contains__,
        binding_exists={
            item["binding_id"] for item in snapshot["bindings"]
        }.__contains__,
        asset_exists={
            item["asset_ref"] for item in snapshot["head"]["assets"]
        }.__contains__,
    )
    additions = [item for item in operations if item.get("op") == "add"]
    repair = next(item for item in additions if item["title"] == "修复结果")
    obligation = next(item for item in additions if item["title"] == "义务变化")

    assert detour["parent_id"] == chapter["component_id"]
    assert repair["kind"] == "entry"
    assert obligation["kind"] == "special"
    assert repair["parent_id"] == detour["component_id"]
    assert obligation["parent_id"] == detour["component_id"]
    assert additions.index(repair) < additions.index(obligation)


def test_checkpoint_operations_preserve_graph_reentry_as_special_section(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    chapter = ensure_node_chapter(
        package_root=package, branch_id="main", node_id="trial_execution",
        title="试验执行",
    )
    source = {
        "assets": [],
        "sections": [{
            "section_id": "reentry", "title": "研究图切换与当前节点重新进入",
            "section_role": "upgrade_reentry", "body": "",
            "links": [], "blocks": [],
        }],
        "gaps": [],
    }
    snapshot = load_snapshot(package_root=package, branch_id="main")
    operations = checkpoint_operations(
        source, parent_id=chapter["component_id"],
        component_exists={item["component_id"] for item in snapshot["components"]}.__contains__,
        binding_exists={item["binding_id"] for item in snapshot["bindings"]}.__contains__,
        asset_exists={item["asset_ref"] for item in snapshot["head"]["assets"]}.__contains__,
    )

    special = next(item for item in operations if item.get("op") == "add")
    assert special["kind"] == "special"
    assert special["display_kind"] == "graph_continuation"


def test_flattened_special_sections_keep_distinct_block_identities() -> None:
    source = {
        "assets": [],
        "gaps": [],
        "sections": [
            {
                "section_id": "gap-entry",
                "title": "能力缺口进入检查",
                "body": "",
                "links": [],
                "blocks": [{
                    "kind": "list",
                    "rows": [{"text": "缺口检查", "link_ids": []}],
                    "report_binding": {
                        "report_requirement_id": "report.requirement.material",
                        "subject_ref": "requirement:material",
                        "report_item_ref": "report-item:sha256:" + "a" * 64,
                    },
                }],
            },
            {
                "section_id": "resolution-entry",
                "title": "能力解决进入检查",
                "body": "",
                "links": [],
                "blocks": [{
                    "kind": "list",
                    "rows": [{"text": "解决检查", "link_ids": []}],
                    "report_binding": {
                        "report_requirement_id": "report.requirement.material",
                        "subject_ref": "requirement:material",
                        "report_item_ref": "report-item:sha256:" + "b" * 64,
                    },
                }],
            },
        ],
    }

    operations = checkpoint_operations(
        source,
        parent_id="capability-detour",
        parent_kind="special",
        component_exists=lambda _value: False,
        binding_exists=lambda _value: False,
        asset_exists=lambda _value: False,
    )
    blocks = [
        item for item in operations
        if item.get("op") == "add"
        and any(
            binding.get("kind") == "report_requirement"
            for binding in item.get("bindings") or []
        )
    ]

    assert len(blocks) == 2
    assert len({item["component_id"] for item in blocks}) == 2
    assert {item["parent_id"] for item in blocks} == {
        "capability-detour"
    }
