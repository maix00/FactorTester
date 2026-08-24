"""Shared client/state helpers for command modules."""

from __future__ import annotations

import click

from tools.cli.client import FactorTesterClient
from tools.cli.agent_auth import load_capability
from tools.cli.http import ClientConfig, HttpSession, load_config
from tools.cli.state import CliState


def requested_ports() -> tuple[int, ...]:
    context = click.get_current_context(silent=True)
    values: list[int] = []
    while context is not None:
        for key in ("ports", "job_ports", "run_ports"):
            values.extend(int(value) for value in (context.params.get(key) or ()))
        context = context.parent
    return tuple(dict.fromkeys(values))


def client_from_config(
    *, port: int | None = None, persist_cookies: bool | None = None,
) -> FactorTesterClient:
    capability = load_capability()
    try:
        config = load_config()
    except FileNotFoundError:
        if capability is None:
            raise
        config = ClientConfig(base_url=capability.base_url)
    if capability is not None:
        # The Manager-issued local endpoint is authoritative for a server
        # Profile.  It prevents the isolated Agent from falling back to the
        # public endpoint and paying for a network round trip.
        config = ClientConfig(base_url=capability.base_url)
    selected = port or (requested_ports()[0] if requested_ports() else None)
    target = config.for_port(selected).base_url if selected else config.base_url
    return FactorTesterClient(
        HttpSession(
            target,
            agent_capability=capability,
            bearer_token=capability.token if capability else "",
            persist_cookies=(
                capability is None
                if persist_cookies is None
                else persist_cookies and capability is None
            ),
        ),
    )


def ensure_child_available(parent: str | None, key: str) -> None:
    modules = client_from_config().list_modules(parent=parent)
    if any(module.get("key") == key for module in modules):
        return
    location = CliState(current_parent=parent).location_label
    raise RuntimeError(f"当前位置 {location} 下没有 {key}；请先 factortester list 查看可进入项。")
