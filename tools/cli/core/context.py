"""Shared client/state helpers for command modules."""

from __future__ import annotations

import click

from tools.cli.client import FactorTesterClient
from tools.cli.http import HttpSession, load_config
from tools.cli.state import CliState


def requested_ports() -> tuple[int, ...]:
    context = click.get_current_context(silent=True)
    values: list[int] = []
    while context is not None:
        for key in ("ports", "job_ports", "run_ports"):
            values.extend(int(value) for value in (context.params.get(key) or ()))
        context = context.parent
    return tuple(dict.fromkeys(values))


def client_from_config(*, port: int | None = None) -> FactorTesterClient:
    config = load_config()
    selected = port or (requested_ports()[0] if requested_ports() else None)
    target = config.for_port(selected).base_url if selected else config.base_url
    return FactorTesterClient(HttpSession(target))


def ensure_child_available(parent: str | None, key: str) -> None:
    modules = client_from_config().list_modules(parent=parent)
    if any(module.get("key") == key for module in modules):
        return
    location = CliState(current_parent=parent).location_label
    raise RuntimeError(f"当前位置 {location} 下没有 {key}；请先 factortester list 查看可进入项。")
