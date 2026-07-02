"""Single-factor-family page CLI controller."""

from __future__ import annotations

import click

from tools.cli.core.context import ensure_child_available
from tools.cli.core.display import print_location_welcome, print_single_factor_family_welcome
from tools.cli.core.errors import friendly_errors
from tools.cli.modules.group_test import enter_group_test_state
from tools.cli.state import load_state, save_state


@click.command("single_factor_family_test")
@click.option("--factor-family", "--factor_family", default="", help="要测试的因子家族。")
@click.argument("path", nargs=-1)
@friendly_errors
def enter_single_factor_family_test(factor_family: str, path: tuple[str, ...]) -> None:
    """Enter the single-factor-family test page controller."""
    if not factor_family:
        factor_family = click.prompt("因子家族", default="", show_default=False)
    if not factor_family:
        raise click.ClickException("必须选择 factor_family")
    state = load_state()
    ensure_child_available(state.current_parent, "single_factor_family_test")
    state.enter("single_factor_family_test")
    state.factor_family = factor_family
    for child in path:
        enter_child(state, child)
    save_state(state)
    if path:
        print_location_welcome(state)
    else:
        print_single_factor_family_welcome(state)


def enter_child(state, key: str) -> None:
    if key == "group_test":
        enter_group_test_state(state)
        return
    ensure_child_available(state.current_parent, key)
    state.enter(key)

