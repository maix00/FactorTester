"""Click entry point for the FactorTester research harness."""

from __future__ import annotations

import click

from . import __version__
from .commands.audit import (
    decision, decision_poor_result, gap, gap_add, gap_list, gap_resolve,
    skill_usage, skill_usage_list, skill_usage_record, status,
)
from .commands.common import echo_json as _echo_json
from .commands.cycle import cycle
from .commands.evidence import evidence
from .commands.external import external_factor, external_factor_plan, external_factor_validate
from .commands.graph import graph, graph_capabilities, graph_draft, graph_observed, graph_replay
from .commands.operations import operator, operator_set, service, service_list, service_restart, workspace, workspace_inspect, workspace_prepare
from .commands.report import report
from .commands.research import checklist, doctor, plan, run_step, slice_plan
from .core.session import DEFAULT_SESSION, load_session
from .utils.repl_skin import ReplSkin


@click.group(invoke_without_command=True)
@click.option("--session", "session_path", default=DEFAULT_SESSION, show_default=True, help="研究 session JSON 文件。")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def cli(ctx: click.Context, session_path: str, as_json: bool) -> None:
    """FactorTester research harness driven by CLI-Anything methodology."""
    ctx.ensure_object(dict)
    ctx.obj["session_path"] = session_path
    ctx.obj["as_json"] = as_json
    if ctx.invoked_subcommand is None:
        session = load_session(session_path)
        if as_json:
            _echo_json(session.to_dict())
            return
        skin = ReplSkin("factortester-research", version=__version__)
        skin.print_banner()
        skin.status("status", session.status)
        skin.status("factor_families", ", ".join(session.factor_families) or "未设置")
        skin.info("Use `plan`, `run-step`, `gap list`, and `status` commands. This harness calls the real `factortester` CLI.")


for command in (
    doctor, plan, graph, slice_plan, skill_usage, run_step, operator, service,
    workspace, decision, gap, status, checklist, external_factor,
    cycle,
    evidence,
    report,
):
    cli.add_command(command)


if __name__ == "__main__":
    cli()
