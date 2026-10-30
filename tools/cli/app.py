"""Click entrypoint for the separately installed TradeResearch CLI."""

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
from tools.cli.commands.strategy_library import strategy_library
from tools.cli.commands.strategy_actor import register_strategy_actor_commands
from tools.cli.commands.margin_budget import margin_budget
from tools.cli.commands.job_orders import register_job_order_commands
from tools.cli.commands.research import external_factor, job, run, workspace
from tools.cli.commands.workspace_strategy import register_workspace_strategy_commands
from tools.cli.commands.direct_trial import trial_plan
from tools.cli.modules.registry import register_cli_modules
from tools.cli.modules.agents import agents
from tools.cli.modules.research import register_research_domain


research = click.Group("research", help="Research reports, evidence, and profiles.")


@click.group()
@click.option(
    "--port", "ports", multiple=True, type=click.IntRange(1, 65535),
    help="Run/Job 的业务服务选择器；由 Manager 校验并路由，不改变服务器入口地址。",
)
def cli(ports: tuple[int, ...]) -> None:
    """TradeResearch CLI.

    \b
    常用路径:
      traderesearch configure --base-url https://manager.example:7998
      traderesearch login
      traderesearch doctor
      traderesearch factor-plan --factor-family SgCCS --configuration-file research-config.json
      # agent 因子研究：安装/使用 longbridge-quant、quantitative-research，并阅读 tools/cli/docs/factor-research-cli.md
      traderesearch list
      traderesearch workspace create --factor-family SgCCS --factor 'SgCCS=SgCCS|N:2m|$F:1d'
      traderesearch workspace update --file research-config.json
      traderesearch run submit --analysis ic --analysis backtest
      traderesearch job list
      traderesearch job watch <job_id>
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
cli.add_command(strategy)
cli.add_command(strategy_library)
strategy.add_command(strategy_intent)
register_strategy_actor_commands(strategy)
cli.add_command(margin_budget)
cli.add_command(workspace)
register_workspace_strategy_commands(workspace)
cli.add_command(external_factor)
cli.add_command(run)
cli.add_command(job)
cli.add_command(research)
register_job_order_commands(job)
register_research_domain(research)
cli.add_command(agents)
cli.add_command(trial_plan)
register_cli_modules(cli)


if __name__ == "__main__":
    cli()
