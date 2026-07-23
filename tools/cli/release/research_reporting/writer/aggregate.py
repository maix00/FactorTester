"""Deterministic Work Package summary rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def render_work_package_report(index: dict[str, Any]) -> bytes:
    lines = [
        f"# 研究工作包 `{index['work_package_id']}`",
        "",
        f"- 工作区：`{index['workspace_id']}`",
        f"- 研究分支：{len(index['branches'])}",
        f"- 省略的检查点章节：{index['omitted_section_count']}",
        "",
    ]
    for branch in index["branches"]:
        lines.extend([
            f"## {branch['title']}",
            "",
            f"- 分支：`{branch['branch_id']}`",
            f"- 状态：`{_status_label(branch['status'])}`",
            f"- 来源哈希：`{branch['source_hash']}`",
            (
                f"- [查看连续研究报告](branches/{branch['branch_id']}"
                f"/REPORT{Path(branch['report_ref']).suffix})"
            ),
            "",
        ])
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _status_label(status: str) -> str:
    return {
        "running": "进行中",
        "active": "进行中",
        "paused": "已暂停",
        "blocked": "等待处理",
        "completed": "已完成",
        "closed": "已完成",
        "failed": "失败",
    }.get(status, status)
