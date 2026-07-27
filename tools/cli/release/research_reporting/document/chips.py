"""Extensible report chip descriptors.

The document stores only a stable chip kind and target. Presentation modules
may add richer fields without making the report document depend on Graph.
"""

from __future__ import annotations

from typing import Any, Callable


ChipPresenter = Callable[[dict[str, Any]], dict[str, Any]]

_DESCRIPTORS: dict[str, dict[str, Any]] = {
    "evidence": {"labels": {"zh-Hans": "证据", "en": "Evidence"}, "icon": "checkmark.seal", "target": "detail"},
    "obligation": {"labels": {"zh-Hans": "义务", "en": "Obligation"}, "icon": "exclamationmark.triangle", "target": "detail"},
    "task": {"labels": {"zh-Hans": "任务", "en": "Task"}, "icon": "checklist", "target": "detail"},
    "job": {"labels": {"zh-Hans": "任务运行", "en": "Job"}, "icon": "clock", "target": "detail"},
    "claim": {"labels": {"zh-Hans": "Claim", "en": "Claim"}, "icon": "quote.bubble", "target": "detail"},
    "artifact": {"labels": {"zh-Hans": "生成物", "en": "Artifact"}, "icon": "doc", "target": "download"},
    "report_requirement": {"labels": {"zh-Hans": "报告要求", "en": "Report requirement"}, "icon": "doc.text", "target": "detail"},
    "graph_reference": {"labels": {"zh-Hans": "研究图", "en": "Research graph"}, "icon": "point.3.connected.trianglepath.dotted", "target": "detail"},
}
_PRESENTERS: dict[str, ChipPresenter] = {}


def register_chip_kind(
    kind: str,
    *,
    label: str,
    icon: str = "tag",
    target: str = "detail",
    presenter: ChipPresenter | None = None,
) -> None:
    """Register a display policy without changing the document schema."""
    if not isinstance(kind, str) or not kind.strip():
        raise ValueError("chip kind must be non-empty")
    _DESCRIPTORS[kind] = {
        "labels": {"zh-Hans": label, "en": label},
        "icon": icon,
        "target": target,
    }
    if presenter is not None:
        _PRESENTERS[kind] = presenter


def chip_kinds() -> list[str]:
    return sorted(_DESCRIPTORS)


def chip_descriptor(chip: dict[str, Any], *, locale: str = "zh-Hans") -> dict[str, Any]:
    kind = str(chip.get("kind") or "")
    base = dict(_DESCRIPTORS.get(
        kind,
        {"labels": {"zh-Hans": kind or "标记", "en": kind or "Tag"}, "icon": "tag", "target": "detail"},
    ))
    presenter = _PRESENTERS.get(kind)
    if presenter is not None:
        base.update(presenter(chip))
    base.update({
        "kind": kind,
        "chip_id": str(chip.get("chip_id") or ""),
        "target_ref": str(chip.get("target_ref") or ""),
        "locale": locale,
        "display_label": str(chip.get("label") or base.get("labels", {}).get(locale) or base["labels"].get("zh-Hans") or kind),
        "labels": dict(base.get("labels") or {}),
    })
    return base
