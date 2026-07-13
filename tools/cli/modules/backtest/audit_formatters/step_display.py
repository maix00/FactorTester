"""Step-mode navigation and badge display helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from tools.cli.modules.backtest.audit_formatters import table_render


@dataclass
class StepNavigator:
    until: datetime | None = None
    to_end: bool = False

    def should_display(self, timestamp: Any) -> bool:
        if self.to_end:
            return False
        if self.until is None:
            return True
        current = parse_step_timestamp(timestamp)
        if current is None or current < self.until:
            return False
        self.until = None
        return True


def parse_step_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        # Compare the wall-clock timestamp exactly as printed by the server;
        # the remote CLI machine may live in a different local timezone.
        parsed = parsed.replace(tzinfo=None)
    return parsed


def set_step_navigation(navigator: StepNavigator, command: str) -> str | None:
    text = command.strip()
    if not text:
        return None
    if text.lower() in {"end", "finish"}:
        navigator.to_end = True
        navigator.until = None
        return None
    if text.lower().startswith("until "):
        target = parse_step_timestamp(text[6:].strip())
        if target is None:
            return "无法解析时刻；示例: until 2026-01-15 10:30:00"
        navigator.until = target
        navigator.to_end = False
        return None
    return "未知命令；使用 Enter、until <时刻> 或 end"


def step_continue_payload(run_token: str, navigator: StepNavigator | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"run_token": run_token, "action": "continue"}
    if navigator is not None and navigator.to_end:
        payload["action"] = "end"
    elif navigator is not None and navigator.until is not None:
        payload["action"] = "until"
        payload["until"] = navigator.until.isoformat(sep=" ")
    return payload


def current_event_subject_summary(current_event: dict[str, Any]) -> str:
    subjects = current_event.get("subjects")
    if not isinstance(subjects, list) or not subjects:
        return "无事件主体"
    parts: list[str] = []
    for item in subjects[:3]:
        if not isinstance(item, dict):
            continue
        strategy = item.get("strategy") or ""
        ledger = item.get("ledger") or ""
        subject = item.get("subject") or ""
        action = item.get("action") or ""
        order_id = item.get("order_id") or ""
        owner = strategy or ledger or "共享"
        detail = str(subject or action or order_id or "?")
        if action and action != subject:
            detail = f"{detail}/{action}" if detail else str(action)
        parts.append(f"{owner}:{detail}")
    remaining = len(subjects) - len(parts)
    if remaining > 0:
        parts.append(f"...另 {remaining} 条")
    return "；".join(parts) if parts else "无事件主体"


def step_badge_box_lines(
    data: dict[str, Any],
    phase_text: str,
    flow_id: str,
    flow_name: str,
    timestamp_text: str,
) -> list[str]:
    current_event = data.get("current_event")
    if not isinstance(current_event, dict):
        current_event = {}
    event_kind = str(current_event.get("event_kind") or data.get("event_kind") or "")
    batch_count = current_event.get("batch_count")
    fields = [
        ("flow", f"{phase_text} · {flow_id} ({flow_name})"),
        ("timestamp", timestamp_text or "-"),
    ]
    if event_kind or batch_count not in (None, ""):
        fields.append(("event_kind", event_kind or "-"))
        fields.append(("batch_count", str(batch_count) if batch_count not in (None, "") else "-"))
        fields.append(("event_subjects", current_event_subject_summary(current_event)))
    key_width = max(table_render.display_width_text(key) for key, _value in fields)
    max_width = table_render.max_width() - 4
    display_lines: list[str] = []
    for key, value in fields:
        line_prefix = f"{table_render.pad_cell(key, key_width)} = "
        line = f"{line_prefix}{value}"
        continuation = " " * table_render.display_width_text(line_prefix)
        display_lines.extend(table_render.wrap_text(line, width=max_width, subsequent_indent=continuation))
    box_width = min(max_width, max(table_render.display_width_text(line) for line in display_lines))
    border = "━" * (box_width + 2)
    return [
        f"┏{border}┓",
        *[f"┃ {table_render.pad_cell(line, box_width)} ┃" for line in display_lines],
        f"┗{border}┛",
    ]
