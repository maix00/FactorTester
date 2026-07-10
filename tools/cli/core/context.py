"""Shared client/state helpers for command modules."""

from __future__ import annotations

from tools.cli.client import FactorTesterClient
from tools.cli.http import HttpSession, load_config
from tools.cli.state import CliState


def client_from_config() -> FactorTesterClient:
    config = load_config()
    return FactorTesterClient(HttpSession(config.base_url))


def ensure_child_available(parent: str | None, key: str) -> None:
    modules = client_from_config().list_modules(parent=parent)
    if any(module.get("key") == key for module in modules):
        return
    location = CliState(current_parent=parent).location_label
    raise RuntimeError(f"当前位置 {location} 下没有 {key}；请先 factortester list 查看可进入项。")

