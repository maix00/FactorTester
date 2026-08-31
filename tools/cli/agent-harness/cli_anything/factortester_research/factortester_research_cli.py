"""Click entry point for the FactorTester research harness."""

from __future__ import annotations

import click

from . import __version__
from .commands.audit import (
    decision,
    gap,
    skill_usage,
    status,
)
from .commands.common import echo_json as _echo_json
from .commands.evidence import evidence
from .commands.external import (
    external_factor,
)
from .commands.graph import (
    graph,
)
from .commands.margin_budget import margin_budget
from .commands.operations import (
    operator,
    service,
)
from .commands.report import report
from .commands.research import checklist, doctor, plan, run_step, slice_plan
from .commands.strategy import strategy
from .commands.strategy_intent import strategy_intent
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
    decision, gap, status, checklist, external_factor,
    evidence,
    report,
    strategy,
    margin_budget,
):
    cli.add_command(command)

strategy.add_command(strategy_intent)


if __name__ == "__main__":
    cli()
