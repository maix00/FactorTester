"""Custom factors home-module CLI controller."""

from __future__ import annotations

from typing import Any

import click

from tools.cli.core.context import client_from_config, ensure_child_available
from tools.cli.core.errors import friendly_errors
from tools.cli.state import load_state, save_state


@click.group("custom_factors", invoke_without_command=True)
@click.pass_context
@friendly_errors
def custom_factors(ctx: click.Context) -> None:
    """Enter custom factors module."""
    if ctx.invoked_subcommand is None:
        state = load_state()
        ensure_child_available(None, "custom_factors")
        state.enter("custom_factors")
        save_state(state)
        click.echo("因子管理")
        click.echo("可用功能: factortester custom_factors factor-library list|add")


@custom_factors.group("factor-library", invoke_without_command=True)
@click.option("--factor-family", "--factor_family", default="", help="因子家族。")
@click.option("--product-group", "--product_group", default="", help="可选产品组 scope。")
@click.pass_context
@friendly_errors
def factor_library(ctx: click.Context, factor_family: str, product_group: str) -> None:
    """Manage factor parameter library from the existing SQL store."""
    ctx.ensure_object(dict)
    ctx.obj["factor_family"] = factor_family
    ctx.obj["product_group"] = product_group
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_factors, factor_family=factor_family, product_group=product_group)


@factor_library.command("list")
@click.option("--factor-family", "--factor_family", default="", help="因子家族。")
@click.option("--product-group", "--product_group", default="", help="可选产品组 scope。")
@click.option("--include-subordinates", is_flag=True, help="包含下级用户可见配置。")
@click.pass_context
@friendly_errors
def list_factors(
    ctx: click.Context,
    factor_family: str,
    product_group: str,
    include_subordinates: bool,
) -> None:
    """List factor parameter candidates."""
    factor_family = factor_family or ctx.obj.get("factor_family", "")
    product_group = product_group or ctx.obj.get("product_group", "")
    overview = client_from_config().factor_library_overview(
        factor_family=factor_family,
        product_group=product_group,
        include_subordinates=include_subordinates,
    )
    factors = overview.get("factors") or []
    if not factors:
        click.echo("暂无因子参数候选")
        return
    for factor in factors:
        click.echo(factor_line(factor, default_family=factor_family, default_product_group=product_group))


@factor_library.command("add")
@click.option("--factor-family", "--factor_family", required=True, help="因子家族。")
@click.option("--product-group", "--product_group", default="", help="可选产品组 scope。")
@click.option("--param", "params", multiple=True, required=True, metavar="KEY=VALUE", help="参数键值，可重复传入。")
@friendly_errors
def add_factor_params(factor_family: str, product_group: str, params: tuple[str, ...]) -> None:
    """Append one parameter row to the factor library."""
    client = client_from_config()
    current_rows = current_user_params(client.factor_library_configs(factor_family, product_group=product_group))
    row = dict(parse_key_value(item) for item in params)
    current_rows.append(row)
    data = client.save_factor_library_config(
        factor_family,
        product_group=product_group,
        params_list=current_rows,
    )
    factors = data.get("factors") or []
    click.echo("已新增因子参数")
    if factors:
        click.echo(factor_line(factors[-1], default_family=factor_family, default_product_group=product_group))


def current_user_params(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for user in payload.get("users") or []:
        if not user.get("editable"):
            continue
        config = user.get("config") or {}
        params = config.get("params_list") or []
        return [dict(row) for row in params if isinstance(row, dict)]
    return []


def factor_line(factor: dict[str, Any], *, default_family: str = "", default_product_group: str = "") -> str:
    alias = factor.get("factor_alias") or factor.get("alias") or factor.get("name")
    family = factor.get("factor_family_alias") or factor.get("factor_family_name") or default_family
    scope = factor.get("product_group") or factor.get("scope_key") or default_product_group or "默认"
    owner = factor.get("owner_alias") or factor.get("owner_username") or ""
    parts = [str(alias)]
    if family:
        parts.append(f"因子家族={family}")
    if scope:
        parts.append(f"产品组={scope}")
    if owner:
        parts.append(f"所有者={owner}")
    return " · ".join(parts)


def parse_key_value(item: str) -> tuple[str, str]:
    if "=" not in item:
        raise click.ClickException("参数必须使用 KEY=VALUE 格式")
    key, value = item.split("=", 1)
    key = key.strip()
    if not key:
        raise click.ClickException("参数 KEY 不能为空")
    return key, value.strip()
