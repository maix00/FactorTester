from __future__ import annotations

from pathlib import Path

from tools.cli.release.research_reporting.authoring.checkpoint_operations import (
    checkpoint_operations,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    apply_batch,
    ensure_node_chapter,
    initialize_tree,
    load_snapshot,
)
from tools.cli.release.research_reporting.authoring.tree_render import (
    render_tree_markdown,
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
                {"kind": "figure", "asset": {"asset_ref": "asset:equity", "caption": "权益曲线"}, "link_ids": ["ev"], "report_binding": {"report_requirement_id": "requirement:equity", "subject_ref": "factor:one", "report_item_ref": "report-item:one"}},
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
    apply_batch(package_root=package, branch_id="main", operations=operations)
    saved = load_snapshot(package_root=package, branch_id="main")
    rendered = render_tree_markdown(saved).decode()
    assert all(value in rendered for value in ("段落内容", "列表内容", "| Sharpe | 1.2 |", "$$\nr_t", "![权益曲线](../../assets/equity.svg)", "仍需补充覆盖率"))
    assert "factortester://evidence/evidence%3Aone" in rendered
    assert "factortester://trial_plan/trial-plan%3Aone" in rendered
    assert "factortester://report_requirement/requirement%3Aequity" in rendered
    assert {item["kind"] for item in saved["bindings"]} >= {"evidence", "trial_plan", "report_requirement"}

    repeated = checkpoint_operations(
        source, parent_id=chapter["component_id"],
        component_exists={item["component_id"] for item in saved["components"]}.__contains__,
        binding_exists={item["binding_id"] for item in saved["bindings"]}.__contains__,
        asset_exists={item["asset_ref"] for item in saved["head"]["assets"]}.__contains__,
    )
    assert repeated == []
