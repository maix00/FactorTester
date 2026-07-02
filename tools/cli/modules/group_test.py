"""Group-test CLI controller."""

from __future__ import annotations

import click

from tools.cli.core.context import ensure_child_available
from tools.cli.core.display import print_group_test_welcome
from tools.cli.core.errors import friendly_errors
from tools.cli.state import load_state, save_state


@click.command("group_test")
@friendly_errors
def enter_group_test() -> None:
    """Enter the group backtest controller from the current page."""
    state = load_state()
    enter_group_test_state(state)
    save_state(state)
    print_group_test_welcome(state)


def enter_group_test_state(state) -> None:
    ensure_child_available(state.current_parent, "group_test")
    state.enter("group_test")

