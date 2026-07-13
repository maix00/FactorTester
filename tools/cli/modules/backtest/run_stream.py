"""Backtest stream event dispatch helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click

from tools.cli.modules.backtest import run_config
from tools.cli.modules.backtest.audit_formatters import step_display


StepEventHandler = Callable[[dict[str, Any], Any, str, step_display.StepNavigator], None]


def handle_stream_event(
    event: dict[str, Any],
    *,
    renderer: Any,
    client: Any,
    run_token: str,
    step_navigator: step_display.StepNavigator,
    handle_step_event: StepEventHandler,
) -> None:
    event_name = str(event.get("event") or "message")
    data = event.get("data")
    if event_name == "error":
        raise click.ClickException(f"分组测试失败: {run_config.stream_error_message(data)}")
    if event_name == "step" and isinstance(data, dict):
        handle_step_event(data, client, run_token, step_navigator)
        return
    if run_config.is_renderer_event(event_name):
        renderer.handle(event_name, data)


def consume_stream(
    client: Any,
    run_payload: dict[str, Any],
    *,
    renderer: Any,
    run_token: str,
    step_navigator: step_display.StepNavigator,
    handle_step_event: StepEventHandler,
) -> None:
    for event in client.run_group_test_stream(run_payload):
        handle_stream_event(
            event,
            renderer=renderer,
            client=client,
            run_token=run_token,
            step_navigator=step_navigator,
            handle_step_event=handle_step_event,
        )
