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
            f"- 状态：`{_status_label(value['status'])}`",
            f"- 产品范围：`{_product_group_label(value['product_group'])}`",
            "- 因子家族版本："
            + ", ".join(
                f"`{item}`" for item in value["factor_family_versions"]
            ),
            "",
        ]
        if value.get("trial_plan_hash"):
            lines.insert(4, "- 历史 TrialPlan：`" + value["trial_plan_hash"] + "`")
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
        if block["kind"] == "math":
            lines.extend([
                "$$", block["latex"], "$$", "", block["fallback"], "",
            ])
        elif block["kind"] == "paragraph":
            lines.extend([block["text"], ""])
        elif block["kind"] == "code":
            fence = "```"
            while fence in block["code"]:
                fence += "`"
            lines.extend([
                f"{fence}{block['language']}", block["code"], fence, "",
            ])
        elif block["kind"] == "list":
            lines.extend(f"- {row['text']}" for row in block["rows"])
            lines.append("")
        elif block["kind"] == "figure":
            # The section asset projection below renders the image once.
            continue
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


def _status_label(value: str) -> str:
    return {
        "running": "进行中",
        "active": "进行中",
        "paused": "已暂停",
        "blocked": "等待处理",
        "completed": "已完成",
        "closed": "已完成",
        "failed": "失败",
    }.get(value, "状态未知")


def _product_group_label(value: str) -> str:
    return {
        "china_futures": "中国期货",
        "cnfutures": "中国期货",
        "china_equities": "中国股票",
        "cnequities": "中国股票",
        "japan_futures": "日本期货",
        "jpfutures": "日本期货",
    }.get(value.lower(), "其他产品组")


def _node_label(value: str) -> str:
    return {
        "candidate_discovery": "候选发现",
        "hypothesis_preregistration": "假设预注册",
        "capability_resolution": "研究能力确认",
        "data_contract": "数据合同",
        "factor_semantics": "因子语义审查",
        "validation_design": "验证设计",
        "trial_plan": "试验计划",
        "capability_gap": "能力缺口",
        "job_evidence_ready": "计算证据就绪",
        "evidence_assessment": "证据评估",
        "factor_improvement": "因子改进",
        "completed": "研究完成",
    }.get(value, "研究进行中")
