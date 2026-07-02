"""Generic backtest CLI controller.

The single-factor-family page currently exposes a `group_test` module key from
the backend.  CLI users should enter the generic `backtest` controller; this
adapter maps that public command to the backend group-test application.
"""

from __future__ import annotations

from typing import Any

import click

from tools.cli.core.context import ensure_child_available
from tools.cli.core.display import print_backtest_welcome
from tools.cli.core.errors import friendly_errors
from tools.cli.modules.keys import BACKTEST_BACKEND_KEY, BACKTEST_PUBLIC_KEY
from tools.cli.state import load_state, save_state


@click.group("backtest", invoke_without_command=True)
@click.option("--factor-family", "--factor_family", default="", help="从顶层进入回测时使用的因子家族。")
@click.option(
    "--config-local-settings",
    "--config_local_settings",
    "local_settings",
    multiple=True,
    metavar="KEY=VALUE",
    help="写入回测 local-settings 草稿，可重复传入。",
)
@click.option("--time-range", "--time_range", nargs=2, metavar="START END", help="写入 local-settings 的起止时间。")
@click.option("--add-group", "--add_group", is_flag=True, help="在当前回测草稿中新增一个分组。")
@click.option("--name", default="", help="新增分组名称。")
@click.option("--split-count", "--split_count", type=int, default=None, help="新增分组的分组数。")
@click.option("--group-index", "--group_index", type=int, default=None, help="新增分组的分组序号。")
@click.pass_context
@friendly_errors
def backtest(
    ctx: click.Context,
    factor_family: str,
    local_settings: tuple[str, ...],
    time_range: tuple[str, str] | None,
    add_group: bool,
    name: str,
    split_count: int | None,
    group_index: int | None,
) -> None:
    """Enter the generic backtest controller."""
    if ctx.invoked_subcommand is not None:
        return
    state = load_state()
    enter_backtest_state(state, factor_family=factor_family)
    _apply_local_settings(state, local_settings, time_range)
    if add_group:
        _append_group(state, name=name, split_count=split_count, group_index=group_index)
    save_state(state)
    print_backtest_welcome(state)


@backtest.command("add-group")
@click.option("--name", default="", help="新增分组名称。")
@click.option("--split-count", type=int, default=None, help="分组数。")
@click.option("--group-index", type=int, default=None, help="分组序号。")
@friendly_errors
def add_group(name: str, split_count: int | None, group_index: int | None) -> None:
    """Start a group-test add-group action in the backtest controller."""
    state = load_state()
    if state.current_parent not in {BACKTEST_BACKEND_KEY, BACKTEST_PUBLIC_KEY}:
        enter_backtest_state(state)
    _append_group(state, name=name, split_count=split_count, group_index=group_index)
    save_state(state)
    click.echo("新增分组")
    _print_group(state.backtest_groups[-1])
    click.echo("下一步: 这些参数会进入 backtest/group-test 的配置草稿；运行接口接好后可直接提交。")


def enter_backtest_state(state, *, factor_family: str = "") -> None:
    if state.current_parent == "single_factor_family_test":
        if factor_family:
            state.factor_family = factor_family
        ensure_child_available(state.current_parent, BACKTEST_BACKEND_KEY)
        state.enter(BACKTEST_BACKEND_KEY)
        return
    if factor_family:
        state.factor_family = factor_family
    if not state.factor_family:
        state.factor_family = click.prompt("因子家族", default="", show_default=False)
    if not state.factor_family:
        raise click.ClickException("从顶层进入 backtest 时必须选择 factor-family")
    ensure_child_available(None, BACKTEST_PUBLIC_KEY)
    state.enter(BACKTEST_PUBLIC_KEY)


def _apply_local_settings(
    state,
    local_settings: tuple[str, ...],
    time_range: tuple[str, str] | None,
) -> None:
    for item in local_settings:
        key, value = _parse_key_value(item)
        state.backtest_local_settings[key] = value
    if time_range is not None:
        start, end = time_range
        state.backtest_local_settings["start_date"] = start
        state.backtest_local_settings["end_date"] = end


def _parse_key_value(item: str) -> tuple[str, str]:
    if "=" not in item:
        raise click.ClickException("--config-local-settings 必须使用 KEY=VALUE 格式")
    key, value = item.split("=", 1)
    key = key.strip()
    if not key:
        raise click.ClickException("--config-local-settings 的 KEY 不能为空")
    return key, value.strip()


def _append_group(state, *, name: str, split_count: int | None, group_index: int | None) -> None:
    payload: dict[str, Any] = {}
    if name:
        payload["name"] = name
    if split_count is not None:
        payload["split_count"] = split_count
    if group_index is not None:
        payload["group_index"] = group_index
    state.backtest_groups.append(payload)


def _print_group(group: dict[str, Any]) -> None:
    if group.get("name"):
        click.echo(f"名称: {group['name']}")
    if group.get("split_count") is not None:
        click.echo(f"分组数: {group['split_count']}")
    if group.get("group_index") is not None:
        click.echo(f"分组序号: {group['group_index']}")
