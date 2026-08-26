"""Agent-facing repair instructions after a human-authorized coverage bypass."""

from __future__ import annotations

from typing import Any


def bypass_remediation(
    *,
    enabled: bool,
    source_chapter_id: str,
    report_requirement_ids: list[str],
    obligation_coverage: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not enabled:
        return None
    missing_obligations = sorted({
        str(item.get("requirement_id") or "")
        for item in obligation_coverage
        if (
            item.get("edge_required")
            and item.get("satisfaction") not in {"satisfied", "limited"}
        )
    } - {""})
    missing_reports = sorted(set(report_requirement_ids) - {""})
    if not missing_reports and not missing_obligations:
        return None
    return {
        "status": "accepted_with_coverage_debt",
        "target_chapter_id": source_chapter_id,
        "missing_report_requirement_ids": missing_reports,
        "missing_obligation_requirement_ids": missing_obligations,
        "instruction": (
            "推进已完成，但这些覆盖项仍须处理。添加报告条目时使用 "
            f"--target-chapter-id {source_chapter_id}；report.requirement.* "
            "仍必须写入 obligation_requirement 特殊小节"
        ),
        "command_template": (
            "factortester research reports add --profile <profile> "
            "--work-package-id <work-package> --branch-id <branch> "
            f"--target-chapter-id {source_chapter_id} "
            "--component-id <component-id> --title <title> ..."
        ),
    }
