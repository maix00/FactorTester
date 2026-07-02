"""Generic backtest CLI controller.

The single-factor-family page currently exposes a `group_test` module key from
the backend.  CLI users should enter the generic `backtest` controller; this
adapter maps that public command to the backend group-test application.
"""

from __future__ import annotations

import click

from tools.cli.core.context import ensure_child_available
from tools.cli.core.display import print_backtest_welcome
from tools.cli.core.errors import friendly_errors
from tools.cli.state import load_state, save_state

BACKTEST_BACKEND_KEY = "group_test"
BACKTEST_PUBLIC_KEY = "backtest"


@click.group("backtest", invoke_without_command=True)
@click.pass_context
@friendly_errors
def backtest(ctx: click.Context) -> None:
    """Enter the generic backtest controller."""
    if ctx.invoked_subcommand is not None:
        return
    state = load_state()
    enter_backtest_state(state)
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
    if state.current_parent != BACKTEST_BACKEND_KEY:
        enter_backtest_state(state)
        save_state(state)
    click.echo("新增分组")
    if name:
        click.echo(f"名称: {name}")
    if split_count is not None:
        click.echo(f"分组数: {split_count}")
    if group_index is not None:
        click.echo(f"分组序号: {group_index}")
    click.echo("下一步: 这些参数会进入 backtest/group-test 的配置草稿；运行接口接好后可直接提交。")


def enter_backtest_state(state) -> None:
    ensure_child_available(state.current_parent, BACKTEST_BACKEND_KEY)
    state.enter(BACKTEST_BACKEND_KEY)

