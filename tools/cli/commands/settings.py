"""Settings manifest inspection and editing commands."""

from __future__ import annotations

from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.field_store import FieldStore, visible_fields
from tools.cli.modules.keys import backend_module_key


@click.command()
@click.argument("key")
@friendly_errors
def describe(key: str) -> None:
    """Describe a tester/backtest setting application."""
    client = client_from_config()
    manifest = client.manifest(backend_module_key(key))
    print_manifest(manifest)


@click.command()
@click.argument("key")
@friendly_errors
def edit(key: str) -> None:
    """Interactively edit server-registered setting fields."""
    client = client_from_config()
    application = backend_module_key(key)
    manifest = client.manifest(application)
    store = FieldStore.from_manifest(manifest)
    tab_lists = manifest.get("tab_lists") or {}
    tabs = list(tab_lists.get("local-settings") or [])
    if not tabs:
        tabs = [{"key": meta.get("tab_key"), "label": meta.get("tab_key")} for meta in store.defaults.values()]
    tabs = _dedupe_tabs(tabs)

    while True:
        click.echo()
        click.echo(f"{key} 设置")
        for index, tab in enumerate(tabs, start=1):
            click.echo(f"  {index}. {tab.get('label') or tab.get('key')}")
        choice = click.prompt("选择 tab（q 退出）", default="q", show_default=False)
        if choice.lower() in {"q", "quit", "exit"}:
            break
        tab = _pick(tabs, choice)
        if tab is None:
            click.echo("无效 tab")
            continue
        tab_key = str(tab.get("key") or "")
        tab_manifest = client.tab_manifest(application, tab_key)
        tab_store = FieldStore.from_manifest(tab_manifest, values=store.explicit_values, parent=store.parent)
        fields = visible_fields(tab_store)
        if not fields:
            click.echo("该 tab 没有可编辑字段")
            continue
        for index, (field_key, meta) in enumerate(fields, start=1):
            click.echo(f"  {index}. {meta.get('label') or field_key}: {tab_store.effective(field_key)!r}")
        field_choice = click.prompt("选择字段（q 返回）", default="q", show_default=False)
        if field_choice.lower() in {"q", "quit", "exit"}:
            continue
        picked = _pick(fields, field_choice)
        if picked is None:
            click.echo("无效字段")
            continue
        field_key, meta = picked
        value = _prompt_value(meta, tab_store.effective(field_key))
        store.set(field_key, value)
        click.echo(f"已设置 {meta.get('label') or field_key}: {value}")

    click.echo("当前显式设置:")
    for field_key, value in store.to_payload().items():
        label = store.field(field_key).get("label", field_key)
        click.echo(f"  {label}: {value}")


def print_manifest(manifest: dict[str, Any]) -> None:
    click.echo(f"应用: {manifest.get('application')}")
    click.echo("Tabs:")
    tab_lists = manifest.get("tab_lists") or {}
    for mount, tabs in tab_lists.items():
        labels = ", ".join(str(tab.get("label") or tab.get("key")) for tab in tabs or [])
        click.echo(f"  {mount}: {labels}")
    click.echo("Settings:")
    store = FieldStore.from_manifest(manifest)
    for field_key, meta in visible_fields(store):
        label = meta.get("label") or field_key
        control = meta.get("control_template") or "unknown"
        click.echo(f"  {field_key} ({label}, {control}) = {store.effective(field_key)!r}")


def _dedupe_tabs(tabs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for tab in tabs:
        key = str(tab.get("key") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(tab)
    return result


def _pick(items: list[Any], choice: str) -> Any | None:
    try:
        index = int(choice)
    except ValueError:
        return None
    if 1 <= index <= len(items):
        return items[index - 1]
    return None


def _prompt_value(meta: dict[str, Any], current: Any) -> Any:
    control = meta.get("control_template")
    options = meta.get("options") or []
    if control == "select" and options:
        for index, option in enumerate(options, start=1):
            click.echo(f"    {index}. {option.get('label') or option.get('value')} [{option.get('value')}]")
        choice = click.prompt("选择值", default="", show_default=False)
        picked = _pick(options, choice)
        if picked is not None:
            return picked.get("value")
        return choice if choice != "" else current
    if control == "number":
        raw = click.prompt("输入数字", default=str(current if current is not None else ""), show_default=False)
        try:
            return int(raw)
        except ValueError:
            return float(raw)
    if control == "boolean":
        return click.confirm("是否启用", default=bool(current))
    return click.prompt("输入值", default=str(current if current is not None else ""), show_default=False)
