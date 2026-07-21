"""Deterministic Markdown target for research reports."""

from __future__ import annotations

from typing import Any

from .schema import MAX_REPORT_BYTES, canonical_report_snapshot


class MarkdownReportTarget:
    """Render one canonical snapshot without external I/O."""

    media_type = "text/markdown"
    extension = ".md"

    def render(self, snapshot: dict[str, Any]) -> bytes:
        value = canonical_report_snapshot(snapshot)
        lines = [
            f"# {value['title']}",
            "",
            f"- 状态：`{value['status']}`",
            f"- 产品范围：`{value['product_group']}`",
            f"- 当前阶段：`{value['current_node']}`",
            (
                "- TrialPlan：`已定义`"
                if value["trial_plan_hash"]
                else "- TrialPlan：`尚未定义`"
            ),
            "- 因子家族版本："
            + ", ".join(
                f"`{item}`" for item in value["factor_family_versions"]
            ),
            "",
        ]
        assets = {
            item["asset_ref"]: item for item in value["assets"]
        }
        for section in value["sections"]:
            lines.extend([f"## {section['title']}", ""])
            if section["body"]:
                lines.extend([section["body"], ""])
            if section.get("blocks"):
                lines.extend(_block_lines(section["blocks"]))
            for asset_ref in section["asset_refs"]:
                lines.extend(_asset_lines(asset_ref, assets.get(asset_ref)))
        if value["gaps"]:
            lines.extend(["## 已知缺口", ""])
            lines.extend(
                f"- `{item['gap_ref']}` — {item['reason']}"
                for item in value["gaps"]
            )
            lines.append("")
        payload = ("\n".join(lines).rstrip() + "\n").encode()
        if len(payload) > MAX_REPORT_BYTES:
            raise ValueError(
                f"rendered report exceeds {MAX_REPORT_BYTES} bytes"
            )
        return payload


def _block_lines(blocks: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for block in blocks:
        if block["kind"] == "paragraph":
            lines.extend([block["text"], ""])
        elif block["kind"] == "list":
            lines.extend(f"- {row['text']}" for row in block["rows"])
            lines.append("")
        else:
            columns = block["columns"]
            lines.extend([
                "| " + " | ".join(columns) + " |",
                "| " + " | ".join("---" for _ in columns) + " |",
            ])
            lines.extend(
                "| " + " | ".join(row["cells"]) + " |"
                for row in block["rows"]
            )
            lines.append("")
    return lines


def _reference_lines(*, title: str, refs: list[str]) -> list[str]:
    if not refs:
        return []
    return [f"### {title}", "", *(f"- `{ref}`" for ref in refs), ""]


def _asset_lines(
    asset_ref: str,
    asset: dict[str, Any] | None,
) -> list[str]:
    if asset is None:
        return [f"- `{asset_ref}` — missing", ""]
    if asset["availability"] != "available":
        return [f"- `{asset_ref}` — {asset['availability']}", ""]
    if asset["media_type"].startswith("image/"):
        return [
            f"![{asset['alt_text']}](../../assets/{asset['filename']})",
            "",
            f"*{asset['caption']}*",
            "",
        ]
    return [
        f"- [{asset['caption']}](../../assets/{asset['filename']})",
        "",
    ]
