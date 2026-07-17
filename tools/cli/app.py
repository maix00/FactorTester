"""Click entrypoint for the separately installed FactorTester CLI."""

from __future__ import annotations

import click

from tools.cli.commands.agent import doctor, factor_plan
from tools.cli.commands.auth import configure, login, logout
from tools.cli.commands.navigation import list_modules
from tools.cli.commands.settings import describe, edit
from tools.cli.commands.research import external_factor, job, run, workspace
from tools.cli.modules.registry import register_cli_modules


@click.group()
def cli() -> None:
    """FactorTester CLI.

    \b
    常用路径:
      factortester configure --host 127.0.0.1 --port 8114
      factortester login --username 18717974771
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
cli.add_command(login)
cli.add_command(logout)
cli.add_command(doctor)
cli.add_command(factor_plan)
cli.add_command(list_modules)
cli.add_command(describe)
cli.add_command(edit)
cli.add_command(workspace)
cli.add_command(external_factor)
cli.add_command(run)
cli.add_command(job)
register_cli_modules(cli)


if __name__ == "__main__":
    cli()
