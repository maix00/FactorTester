"""Click entrypoint for the separately installed FactorTester CLI."""

from __future__ import annotations

import click

from tools.cli.commands.agent import doctor, factor_plan
from tools.cli.commands.auth import configure, login
from tools.cli.commands.navigation import list_modules
from tools.cli.commands.settings import describe, edit
from tools.cli.commands.research import job, run, workspace
from tools.cli.core.errors import backtest_errors as _backtest_errors
from tools.cli.modules.registry import register_cli_modules


@click.group()
def cli() -> None:
    """FactorTester CLI.

    \b
    常用路径:
      factortester configure --host 127.0.0.1 --port 8114
      factortester login --username 18717974771
      factortester doctor
      factortester factor-plan --factor-family SgCCS --template '2026-06-02 07:20:47' --product-group 中国期货日盘 --param N=2m
      # agent 因子研究：安装/使用 longbridge-quant、quantitative-research，并阅读 tools/cli/docs/factor-research-cli.md
      factortester list
      factortester workspace create --factor-family SgCCS
      factortester workspace update --draft-file run-spec.json
      factortester run submit --analysis ic --analysis backtest
      factortester job list
      factortester job watch <job_id>

    factortester list 固定展示首页模块；查看下一层请使用 factortester <module> list 或 --help。

    \b
    字段级帮助示例:
      factortester group --add --group-name --help
      factortester group --add --group-name A1 --help
    """


cli.add_command(configure)
cli.add_command(login)
cli.add_command(doctor)
cli.add_command(factor_plan)
cli.add_command(list_modules)
cli.add_command(describe)
cli.add_command(edit)
cli.add_command(workspace)
cli.add_command(run)
cli.add_command(job)
register_cli_modules(cli)


if __name__ == "__main__":
    cli()
