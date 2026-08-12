"""Compact semantic projections for serialized event drafts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import click

from .values import scalar, table_from_mappings


def render(field: str, value: Any, *, indent: str) -> list[str] | None:
    drafts, total, truncated = _drafts(value)
    if drafts is None:
        return None
    rows = [_draft_row(item) for item in drafts]
    lines = [f"{indent}events={total}", *table_from_mappings(rows, indent=indent)]
    if truncated:
        lines.append(click.style(
            f"{indent}仅显示后端保留的 head/tail 样本；job step-field 可查看原始序列化字段。",
            dim=True,
        ))
    return lines


def _drafts(value: Any) -> tuple[list[Mapping[str, Any]] | None, int, bool]:
    if isinstance(value, list) and value and all(isinstance(item, Mapping) and item.get("type") == "EventDraft" for item in value):
        return value, len(value), False
    if not isinstance(value, Mapping) or value.get("type") != "list":
        return None, 0, False
    sample = value.get("sample")
    if not isinstance(sample, Mapping):
        return None, 0, False
    drafts = [
        item for side in ("head", "tail") for item in sample.get(side) or []
        if isinstance(item, Mapping) and item.get("type") == "EventDraft"
    ]
    return drafts, int(value.get("length") or len(drafts)), bool(value.get("truncated"))


def _draft_row(item: Mapping[str, Any]) -> dict[str, Any]:
    payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
    return {
        "timestamp": item.get("timestamp"),
        "kind": item.get("kind") or payload.get("kind"),
        "strategy": item.get("strategy") or None,
        "ledger": item.get("ledger") or payload.get("ledger_id"),
        "trading_day": payload.get("trading_day"),
        "index_key": scalar(item.get("index_key")),
    }
