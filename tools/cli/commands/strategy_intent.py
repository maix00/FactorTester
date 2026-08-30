"""Inspect and configure manifest-registered strategy intent policies."""

from __future__ import annotations

import json
from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.core.strategy_intent import (
    configure_strategy,
    intent_catalog,
    parse_bindings,
    strategy_rows,
)
from tools.cli.state import load_state, save_state


@click.group("intent")
def strategy_intent() -> None:
    """Inspect and configure registered strategy intent policies."""


@strategy_intent.command("describe")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def describe_strategy_intent(as_json: bool) -> None:
    catalog = intent_catalog(client_from_config().manifest("group_test"))
    if as_json:
        click.echo(_json(catalog))
        return
    click.echo(f"应用: {catalog['application']}")
    for item in catalog["strategy_kinds"]:
        roles = catalog["roles_by_strategy_kind"].get(str(item["value"]), [])
        click.echo(f"{item['value']} ({item['label']}): {', '.join(roles) or '-'}")


@strategy_intent.command("show")
@click.option("--group", "group_id", default="", help="只显示指定策略组。")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def show_strategy_intent(group_id: str, as_json: bool) -> None:
    state, configuration = _configuration()
    rows = strategy_rows(configuration["payload"])
    if group_id:
        rows = [row for row in rows if row["group_id"] == group_id]
        if not rows:
            raise click.ClickException(f"unknown strategy group: {group_id}")
    payload = {"workspace_id": state.workspace_id, "revision": configuration["revision"], "strategies": rows}
    if as_json:
        click.echo(_json(payload))
        return
    for row in rows:
        roles = ", ".join(f"{role}={alias}" for role, alias in row["factor_role_bindings"].items()) or "主因子"
        click.echo(
            f"{row['group_id']} {row['name'] or '-'} kind={row['strategy_kind']} "
            f"factor={row['factor_alias'] or '-'} roles={roles}"
        )


@strategy_intent.command("configure")
@click.argument("group_id")
@click.option("--role", "roles", multiple=True, help="绑定 ROLE=FACTOR_ALIAS，可重复。")
@click.option("--clear-role", "clear_roles", multiple=True, help="清除角色绑定，可重复。")
@click.option("--screen-rule", type=click.Choice(["disabled", "gte", "lte", "between"]))
@click.option("--screen-lower", type=float)
@click.option("--screen-upper", type=float)
@click.option("--allocation-policy", type=click.Choice(["equal_notional", "inverse_volatility", "equal_margin", "factor_sizing"]))
@click.option("--sizing-transform", type=click.Choice(["proportional", "inverse"]))
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def configure_strategy_intent(
    group_id: str, roles: tuple[str, ...], clear_roles: tuple[str, ...],
    screen_rule: str | None, screen_lower: float | None, screen_upper: float | None,
    allocation_policy: str | None, sizing_transform: str | None, as_json: bool,
) -> None:
    if not roles and not clear_roles and all(value is None for value in (
        screen_rule, screen_lower, screen_upper, allocation_policy, sizing_transform,
    )):
        raise click.ClickException("至少提供一个角色绑定、清除项或 policy 设置")
    state, configuration = _configuration()
    client = client_from_config()
    try:
        payload, row = configure_strategy(
            configuration["payload"], intent_catalog(client.manifest("group_test")), group_id,
            bindings=parse_bindings(roles), clear_roles=clear_roles,
            settings={
                "screen_rule": screen_rule, "screen_lower": screen_lower,
                "screen_upper": screen_upper, "allocation_policy": allocation_policy,
                "sizing_transform": sizing_transform,
            },
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    updated = client.update_workspace_configuration(
        state.workspace_id, expected_revision=int(configuration["revision"]), payload=payload,
    )
    state.configuration_revision = int(updated["revision"])
    save_state(state)
    result = {"workspace_id": state.workspace_id, "revision": state.configuration_revision, "strategy": row}
    click.echo(_json(result) if as_json else f"{group_id} updated revision={state.configuration_revision}")


def _configuration():
    state = load_state()
    if not state.workspace_id:
        raise click.ClickException("尚未选择 research workspace；请先运行 factortester workspace create/use")
    return state, client_from_config().get_workspace_configuration(state.workspace_id)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
