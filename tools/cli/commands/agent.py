"""Agent-facing diagnostics and durable research command planning."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.http import config_path, load_config, state_path
from tools.cli.state import load_state
from tools.cli.table import render_table


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: str
    detail: str


@click.command("doctor")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def doctor(as_json: bool) -> None:
    """Check local state and the remote research API."""
    checks = _doctor_checks()
    payload = {
        "success": all(item.status == "ok" for item in checks),
        "checks": [
            {"name": item.name, "status": item.status, "detail": item.detail}
            for item in checks
        ],
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo("FactorTester CLI doctor")
    for line in render_table(
        ("检查项", "状态", "说明"),
        [(item.name, item.status, item.detail) for item in checks],
        indent="  ",
        max_widths=(22, 8, 72),
    ):
        click.echo(line)


def _doctor_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []
    try:
        config = load_config()
        checks.append(CheckResult("config", "ok", f"{config_path()} -> {config.base_url}"))
    except Exception as exc:
        return [CheckResult("config", "fail", str(exc))]
    try:
        client = client_from_config()
        workspaces = client.list_workspaces()
        checks.append(CheckResult("research API", "ok", f"workspaces={len(workspaces)}"))
    except Exception as exc:
        checks.append(CheckResult("research API", "fail", str(exc)))
    try:
        state = load_state()
        selected = state.workspace_id or "未选择"
        checks.append(CheckResult(
            "state", "ok",
            f"{state_path()} workspace_id={selected} configuration_revision={state.configuration_revision}",
        ))
    except Exception as exc:
        checks.append(CheckResult("state", "fail", str(exc)))
    return checks


@click.command("factor-plan")
@click.option("--factor-family", "factor_families", multiple=True, required=True, help="因子家族 alias，可重复。")
@click.option(
    "--configuration-file", required=True, type=click.Path(dir_okay=False),
    help="完整 ResearchConfiguration JSON 文件。",
)
@click.option(
    "--analysis", "analyses", multiple=True,
    type=click.Choice(["backtest", "ic", "factor_evaluation", "factor_type_analysis"]),
    default=("ic", "factor_evaluation", "factor_type_analysis", "backtest"),
    show_default=True,
)
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
def factor_plan(
    factor_families: tuple[str, ...],
    configuration_file: str,
    analyses: tuple[str, ...],
    as_json: bool,
) -> None:
    """Print the durable workspace/run/job command sequence without executing it."""
    plan = _factor_research_plan(
        factor_families=factor_families,
        configuration_file=configuration_file,
        analyses=analyses,
    )
    if as_json:
        click.echo(json.dumps(plan, ensure_ascii=False, indent=2))
        return
    click.echo(f"{', '.join(factor_families)} durable research plan")
    for index, item in enumerate(plan["steps"], start=1):
        click.echo(f"{index}. [{item['phase']}] {item['command']}")


def _factor_research_plan(
    *, factor_families: tuple[str, ...], configuration_file: str, analyses: tuple[str, ...]
) -> dict:
    family_args = " ".join(
        f"--factor-family {shlex.quote(value.strip())}" for value in factor_families
    )
    configuration = shlex.quote(configuration_file)
    analysis_args = " ".join(f"--analysis {shlex.quote(item)}" for item in analyses)
    return {
        "factor_families": [value.strip() for value in factor_families],
        "analyses": list(analyses),
        "steps": [
            {
                "phase": "workspace",
                "command": f"factortester workspace create {family_args}",
            },
            {
                "phase": "configuration",
                "command": f"factortester workspace update --file {configuration}",
            },
            {
                "phase": "run",
                "command": f"factortester run submit {analysis_args}",
            },
            {
                "phase": "observe",
                "command": "factortester job list && factortester job watch <job_id>",
            },
            {
                "phase": "result",
                "command": "factortester job status <job_id> && factortester job artifact <job_id> <name>",
            },
        ],
        "notes": [
            "configuration revision is an optimistic-lock counter; each run freezes the payload.",
            "jobs are queried, cancelled, retried, and continued by job_id.",
            "CLI runs are durable and do not depend on a browser page lease.",
        ],
    }
