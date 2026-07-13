"""Runtime helpers for step-mode backtest execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import click

from tools.cli.modules.backtest.audit_formatters import step_display


PROMPT_TEXT = "命令: Enter=下一步 | until <时刻>=快进到时刻 | end=快进到底"


@dataclass(frozen=True)
class StepEventRenderer:
    phase_label: Callable[[str], str]
    audit_context: Callable[[dict[str, Any]], Any]
    print_badge_box: Callable[[dict[str, Any], str, str, str, str], None]
    print_strategy_context: Callable[[list[dict[str, Any]]], None]
    print_event_payloads: Callable[[list[dict[str, Any]]], None]
    print_audit_fields: Callable[..., None]
    print_audit_changes: Callable[..., None]
    print_contract_audit: Callable[[list[dict[str, Any]]], None]
    display_key: step_display.DisplayKey
    normalize: step_display.Normalize

    def render(self, data: dict[str, Any]) -> None:
        flow_phase = str(data.get("flow_phase") or "")
        flow_name = str(data.get("flow_name") or "")
        flow_id = str(data.get("flow_id") or "")
        phase_text = f"{flow_phase.upper()} ({self.phase_label(flow_phase)})"
        timestamp_text = str(data.get("timestamp") or "")
        click.echo("")
        self.print_badge_box(data, phase_text, flow_id, flow_name, timestamp_text)
        description = str(data.get("description") or "")
        if description:
            click.echo(f"说明: {description}")

        with self.audit_context(data):
            self.print_strategy_context(list(data.get("strategies") or []))
            self.print_event_payloads(list(data.get("event_payloads") or []))
            route_state: set[tuple[tuple[str, str, str], ...]] = set()
            self.print_audit_fields(
                "输入字段",
                list(data.get("inputs") or []),
                empty_message="（此 flow 未声明输入字段）",
                route_state=route_state,
            )
            unchanged_outputs, output_changes, unchanged_message = step_display.output_audit_sections(
                data,
                display_key=self.display_key,
                normalize=self.normalize,
            )
            self.print_audit_fields(
                "声明输出字段（未变化）",
                unchanged_outputs,
                empty_message=unchanged_message,
                route_state=route_state,
            )
            self.print_audit_changes("声明输出的变化", output_changes, route_state=route_state)
            self.print_contract_audit(list(data.get("input_contract_violations") or []))


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
