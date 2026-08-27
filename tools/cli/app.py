"""Click entrypoint for the separately installed FactorTester CLI."""

from __future__ import annotations

import click

from tools.cli.commands.agent import doctor, factor_plan
from tools.cli.commands.auth import configure, login, logout
from tools.cli.commands.assist import assist
from tools.cli.commands.client_release import client
from tools.cli.commands.navigation import list_modules
from tools.cli.commands.protocol import protocol
from tools.cli.commands.settings import describe, edit
from tools.cli.commands.strategy_intent import strategy_intent
from tools.cli.commands.strategy import strategy
from tools.cli.commands.strategy_actor import register_strategy_actor_commands
from tools.cli.commands.margin_budget import margin_budget
from tools.cli.commands.job_orders import register_job_order_commands
from tools.cli.commands.research import external_factor, job, run, workspace
from tools.cli.commands.research_step import research
from tools.cli.commands.direct_trial import trial_plan
from tools.cli.modules.registry import register_cli_modules
from tools.cli.modules.agents import agents
from tools.cli.modules.research import register_research_domain


def _research_graph_command():
    """Load the optional Research Harness-backed command group.

    The client wheel must remain usable on its own for authentication,
    protocol, catalog and job operations.  Research Graph commands use the
    separately shipped Harness package; keeping that import lazy prevents a
    missing optional package from breaking the whole client CLI.
    """
    try:
        from tools.cli.commands.research_graph import research_graph as command
    except ModuleNotFoundError as exc:
        if not (exc.name or "").startswith("cli_anything"):
            raise

        @click.group("research-graph")
        def command() -> None:
            """研究图命令需要安装匹配版本的 Research Harness。"""

        @command.command("install-help")
        def install_help() -> None:
            raise click.ClickException(
                "research-graph requires the matching "
                "cli-anything-factortester-research package; install the "
                "release bundle with scripts/install_factortester_pipx.sh"
            )
    return command


@click.group()
@click.option(
    "--port", "ports", multiple=True, type=click.IntRange(1, 65535),
    help="目标 FactorTester 端口；可重复指定，job list 会聚合多个端口。",
)
def cli(ports: tuple[int, ...]) -> None:
    """FactorTester CLI.

    \b
    常用路径:
      factortester configure --host 127.0.0.1 --port 8114
      factortester login --username <username>
      factortester doctor
      factortester factor-plan --factor-family SgCCS --configuration-file research-config.json
      # agent 因子研究：安装/使用 longbridge-quant、quantitative-research，并阅读 tools/cli/docs/factor-research-cli.md
      factortester list
      factortester workspace create --factor-family SgCCS --factor 'SgCCS=SgCCS|N:2m|$F:1d'
      factortester workspace update --file research-config.json
      factortester run submit --analysis ic --analysis backtest
      factortester job list
      factortester job watch <job_id>
    用户配置统一保存为 ResearchConfiguration；模板使用同一 schema，提交后由 immutable RunSpec 与 job 承接。
    """


cli.add_command(configure)
cli.add_command(assist)
cli.add_command(client)
cli.add_command(login)
cli.add_command(logout)
cli.add_command(doctor)
cli.add_command(factor_plan)
cli.add_command(list_modules)
cli.add_command(protocol)
cli.add_command(describe)
cli.add_command(edit)
cli.add_command(strategy_intent)
cli.add_command(strategy)
register_strategy_actor_commands(strategy)
cli.add_command(margin_budget)
cli.add_command(workspace)
cli.add_command(external_factor)
cli.add_command(run)
cli.add_command(job)
cli.add_command(research)
register_job_order_commands(job)
register_research_domain(research, graph_command=_research_graph_command())
cli.add_command(agents)
cli.add_command(trial_plan)
register_cli_modules(cli)


if __name__ == "__main__":
    cli()
