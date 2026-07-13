"""Step-mode navigation and badge display helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from tools.cli.modules.backtest.audit_formatters import table_render


DisplayKey = Callable[[Any], str]
Normalize = Callable[[Any], Any]
CashSummary = Callable[[Any], str]


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


def contract_audit_lines(violations: list[dict[str, Any]]) -> list[str]:
    if not violations:
        return ["  已通过：本 flow 未读取未声明输入字段，也未写入未声明输出字段"]
    lines: list[str] = []
    for violation in violations:
        access = str(violation.get("access") or "")
        action = "读取未声明输入" if access == "read" else "写入未声明输出" if access == "write" else f"未声明 {access}"
        field = violation.get("field") or "?"
        lines.append(f"  {action}: {field}")
    return lines


def unchanged_output_records(
    records: list[dict[str, Any]],
    changes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    changed_fields = {str(change.get("field") or "") for change in changes}
    return [record for record in records if str(record.get("field") or "") not in changed_fields]


def unchanged_output_message(outputs: list[dict[str, Any]], output_changes: list[dict[str, Any]]) -> str:
    if not outputs:
        return "（此 flow 未声明输出字段）"
    if output_changes:
        return "（所有声明输出字段均发生变化，见下方“声明输出的变化”）"
    return "（没有未变化的声明输出字段）"


def merge_declared_and_ledger_changes(
    output_changes: list[dict[str, Any]],
    ledger_changes: list[dict[str, Any]],
    *,
    display_key: DisplayKey,
    normalize: Normalize,
) -> list[dict[str, Any]]:
    """Merge declared output and ledger side-channel changes without duplicates."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for change in [*output_changes, *ledger_changes]:
        key = step_change_identity(change, display_key=display_key, normalize=normalize)
        if key in seen:
            continue
        seen.add(key)
        merged.append(change)
    return merged


def step_change_identity(
    change: dict[str, Any],
    *,
    display_key: DisplayKey,
    normalize: Normalize,
) -> str:
    owner = {
        key: change.get(key)
        for key in ("field", "scope", "strategy", "ledger", "cash_pool", "subject", "action", "order_id")
        if change.get(key) not in (None, "")
    }
    return display_key({
        "owner": owner,
        "before": normalize(change.get("before")),
        "after": normalize(change.get("after")),
    })


def strategy_context_lines(
    strategies: list[dict[str, Any]],
    *,
    short_alias_map: dict[str, str],
) -> list[str]:
    if not strategies:
        return ["  （此 flow 尚未关联策略）"]
    aliases: list[str] = []
    for strategy in strategies:
        alias = active_strategy_short_alias(strategy, short_alias_map=short_alias_map)
        if alias and alias not in aliases:
            aliases.append(alias)
    return [f"  {', '.join(aliases) if aliases else '（无）'}"]


def active_strategy_short_alias(strategy: dict[str, Any], *, short_alias_map: dict[str, str]) -> str:
    for key in ("shortAlias", "short_alias", "alias", "display_name", "name"):
        value = str(strategy.get(key) or "").strip()
        if value:
            return value
    strategy_id = str(strategy.get("strategy") or strategy.get("id") or "").strip()
    if strategy_id and strategy_id in short_alias_map:
        return short_alias_map[strategy_id]
    return strategy_id or "?"


def build_short_alias_map(groups: list[dict[str, Any]], ls_configs: list[dict[str, Any]] | None) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for group in groups:
        group_id = str(group.get("id", "") or "")
        short_alias = str(group.get("shortAlias", "") or "")
        if group_id and short_alias:
            aliases[group_id] = short_alias
    for config in ls_configs or []:
        config_id = str(config.get("id", "") or "")
        short_alias = str(config.get("shortAlias", "") or "")
        if config_id and short_alias:
            aliases[config_id] = short_alias
    return aliases


def payloads_empty(value: Any) -> bool:
    return value in (None, [], [None], [None, None])


def non_empty_event_payloads(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [payload for payload in payloads if not payloads_empty(payload.get("payloads"))]


def event_payload_label(payload: dict[str, Any]) -> str:
    if payload.get("scope") == "strategy":
        return f"策略 {payload.get('strategy') or '?'}"
    return f"账本 {payload.get('ledger') or '?'} | 现金池 {payload.get('cash_pool') or '?'}"


def ledger_snapshot_rows(ledgers: list[dict[str, Any]], *, cash_summary: CashSummary) -> list[tuple[Any, ...]]:
    return [
        (
            ledger.get("ledger") or "?",
            ledger.get("cash_pool") or "?",
            ", ".join(ledger.get("strategies") or []) or "无",
            cash_summary(ledger.get("cash")),
        )
        for ledger in ledgers
    ]


def event_payload_change_buckets(
    changes: list[dict[str, Any]],
    *,
    display_key: DisplayKey,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for change in changes:
        key = (display_key(change.get("before")), display_key(change.get("after")))
        bucket = grouped.setdefault(key, {"before": change.get("before"), "after": change.get("after"), "entries": []})
        bucket["entries"].append(change)
    return list(grouped.values())
