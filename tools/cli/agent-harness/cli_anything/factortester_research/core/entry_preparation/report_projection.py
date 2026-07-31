"""Build Chinese report bindings and hashes from validated assessments."""

from __future__ import annotations

import re
from typing import Any

from tools.cli.release.research_reporting.report_items import (
    report_item_hash,
)
from tools.cli.release.report_link_kinds import report_link_kind_for_ref

from .fields import chinese_text, object_field, text_array


def build_report_items(
    *,
    item: dict[str, Any],
    prefix: str,
    obligation_refs: list[str],
    fallback_fact_refs: list[str],
    action: dict[str, str],
    chapter_ref: str,
) -> list[dict[str, Any]]:
    report = object_field(item, "report", prefix)
    report_id = str(report.get("report_requirement_id") or "").strip()
    if not report_id:
        raise ValueError(f"{prefix}.report.report_requirement_id is required")
    if report.get("content_kind") != "list":
        raise ValueError(f"{prefix}.report.content_kind must be list")
    title_zh = chinese_text(
        item.get("title_zh"),
        f"{prefix}.title_zh",
    )
    rows = report.get("content_zh")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{prefix}.report.content_zh must be a non-empty array")
    chinese_rows = [
        _validated_code_aware_prose(
            chinese_text(value, f"{prefix}.report.content_zh"),
            field=f"{prefix}.report.content_zh",
        )
        for value in rows
    ]
    report_refs = text_array(
        report.get("fact_refs"),
        f"{prefix}.report.fact_refs",
    )
    refs = list(dict.fromkeys([
        *report_refs,
        *fallback_fact_refs,
        *filter(None, [action["action_ref"], action["trial_ref"]]),
    ]))
    if not refs:
        raise ValueError(f"{prefix}.report needs at least one reference")
    links = _links(refs)
    content = {
        "kind": "list",
        "rows": [
            {
                "text": text,
                "link_ids": (
                    [link["link_id"] for link in links]
                    if index == 0 else [links[0]["link_id"]]
                ),
            }
            for index, text in enumerate(chinese_rows)
        ],
    }
    subjects = obligation_refs or [f"requirement:{prefix}"]
    return [
        _report_item(
            report_id=report_id,
            title_zh=title_zh,
            subject=subject,
            content=content,
            chinese_rows=chinese_rows,
            links=links,
            chapter_ref=chapter_ref,
        )
        for subject in subjects
    ]


def _report_item(
    *,
    report_id: str,
    title_zh: str,
    subject: str,
    content: dict[str, Any],
    chinese_rows: list[str],
    links: list[dict[str, str]],
    chapter_ref: str,
) -> dict[str, Any]:
    return {
        "report_requirement_id": report_id,
        # Local presentation metadata is deliberately excluded from the
        # compact server submission and report-item identity. Graph-owned
        # requirement titles can therefore improve the local chapter heading
        # without changing the audited research fact or its hash.
        "title_zh": title_zh,
        "subject_ref": subject,
        "content_kind": "list",
        "item_hash": report_item_hash(
            report_requirement_id=report_id,
            subject_ref=subject,
            content_kind="list",
            content=content,
        ),
        "content": content,
        "content_zh": chinese_rows,
        "links": links,
        "report_binding": {
            "report_requirement_id": report_id,
            "subject_ref": subject,
        },
        "chapter_ref": chapter_ref,
    }


def _links(refs: list[str]) -> list[dict[str, str]]:
    return [
        {
            "link_id": f"entry-ref-{index}",
            "kind": report_link_kind_for_ref(ref),
            "target_ref": ref,
            "label": _reference_label(ref),
        }
        for index, ref in enumerate(refs, start=1)
    ]


def _reference_label(value: str) -> str:
    if value.startswith("evidence:"):
        return "证据"
    if value.startswith("trace:"):
        return "节点检查"
    if value.startswith("report:"):
        return "报告记录"
    if value.startswith("factor-expression:"):
        return "因子表达式事实"
    if value.startswith("data-column:"):
        return "因子输入数据列事实"
    if value.startswith("trial:"):
        return "首个 Trial"
    if value.startswith("cli:"):
        return "CLI 事实"
    return "研究事实"


_FACTOR_META_PARAMETER = re.compile(
    r"(?<![`A-Za-z0-9_])\$(F|Rev)(?![A-Za-z0-9_])"
)


def _validated_code_aware_prose(value: str, *, field: str) -> str:
    """Reject ambiguous FactorTester meta parameters in report prose.

    The canonical authoring object must carry its own Markdown semantics.
    Projection is deterministic and must not silently rewrite source facts.
    Structural IDs and aliases never pass through this prose validator.
    """
    match = _FACTOR_META_PARAMETER.search(value)
    if match is not None:
        raise ValueError(
            f"{field} must wrap FactorTester meta parameter "
            f"{match.group(0)} in Markdown inline code"
        )
    return value
