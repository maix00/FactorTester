"""Top-level factor-library command group."""

from __future__ import annotations

import click

from tools.cli.core.errors import friendly_errors

from .catalog import register_factor_library_catalog_commands


@click.group("factor-library", invoke_without_command=True)
@click.option("--factor-family", "--factor_family", default="", help="因子家族。")
@click.option("--product-group", "--product_group", default="", help="可选产品组 scope。")
@click.pass_context
@friendly_errors
def factor_library(
    ctx: click.Context,
    factor_family: str,
    product_group: str,
) -> None:
    """Browse server factor-library objects using Web/Swift permissions."""
    ctx.ensure_object(dict)
    ctx.obj["factor_family"] = factor_family
    ctx.obj["product_group"] = product_group
    if ctx.invoked_subcommand is None:
        click.echo("因子库")
        click.echo("  families          因子家族（公共/我的/下一级用户）")
        click.echo("  factors           已登记因子（公共/我的/下一级用户）")
        click.echo("  factor-sets       因子集合（我的/下一级用户）")
        click.echo("  describe          查看因子家族源码摘要与表达式")
        click.echo("  operators         查看 FactorExpr 算子")
        click.echo("  workspace         管理因子工作区与 Git")


register_factor_library_catalog_commands(factor_library)
