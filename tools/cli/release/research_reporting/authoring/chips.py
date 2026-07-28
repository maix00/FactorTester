"""Presentation descriptors for report-tree chips."""

from __future__ import annotations

from typing import Any


_DESCRIPTORS = {
    "evidence": ("证据", "Evidence", "checkmark.seal", "detail"),
    "obligation": ("义务", "Obligation", "exclamationmark.triangle", "detail"),
    "task": ("任务", "Task", "checklist", "detail"),
    "job": ("任务运行", "Job", "clock", "detail"),
    "claim": ("主张", "Claim", "quote.bubble", "detail"),
    "artifact": ("生成物", "Artifact", "doc", "download"),
    "report_requirement": ("报告要求", "Report requirement", "doc.text", "detail"),
    "graph_reference": ("研究图", "Research graph", "point.3.connected.trianglepath.dotted", "detail"),
    "checkpoint": ("节点检查", "Node checkpoint", "circle.dotted", "detail"),
    "run": ("运行", "Run", "play.circle", "detail"),
    "run_spec": ("运行配置", "Run specification", "slider.horizontal.3", "detail"),
    "trial_plan": ("试验计划", "Trial plan", "list.clipboard", "detail"),
    "delta": ("变化", "Delta", "arrow.left.arrow.right", "detail"),
}


def chip_kinds() -> list[str]:
    return sorted(_DESCRIPTORS)


def chip_descriptor(chip: dict[str, Any], *, locale: str = "zh-Hans") -> dict[str, Any]:
    kind = str(chip.get("kind") or "")
    chinese, english, icon, target = _DESCRIPTORS.get(
        kind, (kind or "标记", kind or "Tag", "tag", "detail"),
    )
    return {
        "kind": kind, "chip_id": str(chip.get("chip_id") or ""),
        "target_ref": str(chip.get("target_ref") or ""), "locale": locale,
        "display_label": str(chip.get("label") or (chinese if locale == "zh-Hans" else english)),
        "labels": {"zh-Hans": chinese, "en": english},
        "icon": icon, "target": target,
    }
