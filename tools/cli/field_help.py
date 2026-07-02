"""Render backend-registered field metadata for CLI help.

The CLI should not own business-field help.  It receives the same public
field manifest as the web UI and only renders that contract into flags,
types, defaults, visibility and editability hints.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tools.cli.field_store import FieldStore


def field_flag(key: str) -> str:
    return f"--{key.replace('_', '-')}"


def field_type_label(meta: Mapping[str, Any]) -> str:
    options = meta.get("options") or []
    values = [
        str(option.get("value"))
        for option in options
        if isinstance(option, Mapping) and option.get("value") is not None
    ]
    if values:
        return "Literal[" + ", ".join(values) + "]"

    control = str(meta.get("control_template") or "").lower()
    if control in {"number", "float"}:
        return "number"
    if control in {"integer", "int"}:
        return "int"
    if control in {"boolean", "bool", "checkbox", "toggle"}:
        return "bool"
    if control in {"date"}:
        return "date"
    if control in {"datetime"}:
        return "datetime"
    if control in {"time"}:
        return "time"
    if control in {"select", "radio", "segmented"}:
        return "Literal[...]"
    if control in {"text", "input", "string"}:
        return "str"
    if control:
        return control
    return "Any"


def render_field_help_line(store: FieldStore, key: str, meta: Mapping[str, Any]) -> str:
    label = str(meta.get("label") or key)
    editable = "可编辑" if store.is_editable(key) else "不可编辑"
    default = meta.get("value")
    current = store.effective(key)
    parts = [
        f"  {field_flag(key)}",
        label,
        f"[{editable}]",
        f"类型={field_type_label(meta)}",
        f"默认={default!r}",
        f"当前={current!r}",
    ]
    if meta.get("visible_when"):
        parts.append(f"显示条件={meta['visible_when']!r}")
    if meta.get("editable_when") or meta.get("editible_when"):
        parts.append(f"编辑条件={meta.get('editable_when', meta.get('editible_when'))!r}")
    help_text = meta.get("help_text")
    if help_text:
        parts.append(f"说明={help_text}")
    return "  ".join(parts)


def render_settings_help(store: FieldStore, *, title: str) -> list[str]:
    lines = [title]
    tabs = _tabs_for_store(store)
    for tab in tabs:
        tab_key = str(tab.get("key") or "")
        fields = _visible_fields_for_tab(store, tab_key)
        if not fields:
            continue
        lines.append(f"{tab.get('label') or tab_key}:")
        for field_key, meta in fields:
            lines.append(render_field_help_line(store, field_key, meta))
    return lines


def _tabs_for_store(store: FieldStore) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for meta in store.defaults.values():
        tab_key = str(meta.get("tab_key") or meta.get("tab") or "default")
        if tab_key not in by_key:
            by_key[tab_key] = {"key": tab_key, "label": meta.get("tab_label") or tab_key}
    return sorted(by_key.values(), key=lambda tab: str(tab.get("label") or tab.get("key") or ""))


def _visible_fields_for_tab(store: FieldStore, tab_key: str) -> list[tuple[str, dict[str, Any]]]:
    from tools.cli.field_store import visible_fields

    return visible_fields(store, tab_key=tab_key) if tab_key else visible_fields(store)
