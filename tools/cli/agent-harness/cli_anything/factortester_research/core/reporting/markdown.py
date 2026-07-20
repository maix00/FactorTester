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
            f"- Status: `{value['status']}`",
            f"- Graph: `{value['graph_ref']}`",
            f"- Source hash: `{value['source_hash']}`",
            f"- Methodology: `{value['methodology_hash']}`",
            f"- Decision Contract: `{value['decision_contract_hash']}`",
            f"- TrialPlan: `{value['trial_plan_hash']}`",
            "- Factor-family versions: "
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
            lines.extend(_reference_lines(
                title="Evidence",
                refs=section["evidence_refs"],
            ))
            for asset_ref in section["asset_refs"]:
                lines.extend(_asset_lines(asset_ref, assets.get(asset_ref)))
        lines.extend(_reference_lines(
            title="All evidence references",
            refs=value["evidence_refs"],
        ))
        if value["gaps"]:
            lines.extend(["## Bounded gaps", ""])
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
