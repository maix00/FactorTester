"""Runtime helpers for step-mode backtest execution."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click

from tools.cli.modules.backtest.audit_formatters import step_display


PROMPT_TEXT = "命令: Enter=下一步 | until <时刻>=快进到时刻 | end=快进到底"


def continue_step(client: Any, run_token: str, navigator: step_display.StepNavigator | None = None) -> None:
    payload = step_display.step_continue_payload(run_token, navigator)
    try:
        client.session.post("/step_continue", payload)
    except Exception as exc:
        raise click.ClickException(f"无法继续单步回测: {exc}") from exc


def prompt_step_navigation(
    navigator: step_display.StepNavigator,
    *,
    read_input: Callable[[str], str] | None = None,
    echo: Callable[[str], None] = click.echo,
) -> None:
    if read_input is None:
        read_input = input
    while True:
        echo(PROMPT_TEXT)
        error = step_display.set_step_navigation(navigator, read_input("step> "))
        if error is None:
            return
        echo(f"  {error}")
