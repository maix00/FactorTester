"""Root backtest command orchestration."""

from __future__ import annotations

from collections.abc import Callable

import click

from tools.cli.core.display import print_backtest_welcome
from tools.cli.state import BACKTEST_SPACE, load_state, save_state, switch_backtest_space


RunBacktest = Callable[..., None]
EnterState = Callable[..., None]


def handle_root_command(
    ctx: click.Context,
    *,
    run: bool,
    step: bool,
    verbose: bool,
    run_backtest: RunBacktest,
    enter_state: EnterState,
) -> None:
    if ctx.invoked_subcommand is not None:
        state = load_state()
        switch_backtest_space(state, BACKTEST_SPACE)
        save_state(state)
        return
    state = load_state()
    enter_state(state, scope=BACKTEST_SPACE)
    save_state(state)
    if run:
        run_backtest(state, groups=state.backtest_groups, verbose=verbose, step_mode=step)
        return
    print_backtest_welcome(state)
