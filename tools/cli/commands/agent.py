"""Agent-facing CLI helpers for FactorTester."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from typing import Any

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
    """Check local CLI state and remote FactorTester API availability."""
    checks = _doctor_checks()
    payload = {
        "success": all(item.status == "ok" for item in checks),
        "checks": [{"name": item.name, "status": item.status, "detail": item.detail} for item in checks],
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


def _factor_plan_options(func):
    func = click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")(func)
    func = click.option(
        "--volume-capacity-mode",
        "--liquidity-mode",
        "liquidity_mode",
        type=click.Choice(["inherit", "infinite", "volume_participation"]),
        default="inherit",
        show_default=True,
        help="成交量容量模式；--liquidity-mode 是旧别名。",
    )(func)
    func = click.option("--top", default=12, type=int, show_default=True, help="每个 grid 输出前 N 项。")(func)
    func = click.option("--rev/--no-rev", default=True, show_default=True, help="是否使用 $Rev。")(func)
    func = click.option("--f", "f_values", multiple=True, help="$F 参数候选，可重复。")(func)
    func = click.option("--param", "params", multiple=True, help="业务因子参数 KEY=VALUE，可重复，例如 --param N=2m。")(func)
    func = click.option("--product-group", "product_groups", multiple=True, help="产品路径候选，可重复。")(func)
    func = click.option("--template", default="", help="可选：先从 single_factor_test 模板加载，例如 '2026-06-02 07:20:47'。")(func)
    func = click.option("--factor-family", required=True, help="因子家族名，例如 SgCCS。")(func)
    return func


@click.command("factor-plan")
@_factor_plan_options
def factor_plan(
    factor_family: str,
    template: str,
    product_groups: tuple[str, ...],
    params: tuple[str, ...],
    f_values: tuple[str, ...],
    rev: bool,
    top: int,
    liquidity_mode: str,
    as_json: bool,
) -> None:
    """Print a non-executing factor research command plan."""
    _print_factor_plan(
        factor_family=factor_family,
        template=template,
        product_groups=product_groups,
        params=params,
        f_values=f_values,
        rev=rev,
        top=top,
        liquidity_mode=liquidity_mode,
        as_json=as_json,
    )


def _print_factor_plan(
    *,
    factor_family: str,
    template: str,
    product_groups: tuple[str, ...],
    params: tuple[str, ...],
    f_values: tuple[str, ...],
    rev: bool,
    top: int,
    liquidity_mode: str,
    as_json: bool,
) -> None:
    plan = _factor_research_plan(
        factor_family=factor_family,
        template=template,
        product_groups=product_groups,
        params=params,
        f_values=f_values,
        rev=rev,
        top=top,
        liquidity_mode=liquidity_mode,
    )
    if as_json:
        click.echo(json.dumps(plan, ensure_ascii=False, indent=2))
        return
    click.echo(f"{plan['factor_family']} CLI 执行计划")
    for note in plan["notes"]:
        click.echo(f"  - {note}")
    click.echo("")
    for index, item in enumerate(plan.get("steps") or [], start=1):
        click.echo(f"{index}. [{item['phase']}] {item['title']}")
        click.echo(f"   {item['command']}")


def _doctor_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []
    try:
        config = load_config()
        checks.append(CheckResult("config", "ok", f"{config_path()} -> {config.base_url}"))
    except Exception as exc:
        checks.append(CheckResult("config", "fail", str(exc)))
        return checks
    try:
        modules = client_from_config().home_modules()
        checks.append(CheckResult("server", "ok", f"home modules={len(modules)}"))
    except Exception as exc:
        checks.append(CheckResult("server", "fail", str(exc)))
    try:
        state = load_state()
        workspace = state.workspace_id or "未选择"
        checks.append(CheckResult("state", "ok", f"{state_path()} workspace_id={workspace}"))
        checks.append(CheckResult("backtest draft", "ok", f"groups={len(state.backtest_groups)}, ls={len(state.backtest_ls_configs)}, space={state.active_backtest_space}"))
    except Exception as exc:
        checks.append(CheckResult("state", "fail", str(exc)))
    try:
        client = client_from_config()
        for key in ("single_factor_page", "group_test", "ic_test", "factor_type_analysis"):
            manifest = client.manifest(key)
            defaults = manifest.get("defaults") if isinstance(manifest, dict) else None
            checks.append(CheckResult(f"manifest:{key}", "ok", f"fields={len(defaults or {})}"))
    except Exception as exc:
        checks.append(CheckResult("manifest", "warn", str(exc)))
    return checks


def _factor_research_plan(
    *,
    factor_family: str,
    template: str,
    product_groups: tuple[str, ...],
    params: tuple[str, ...],
    f_values: tuple[str, ...],
    rev: bool,
    top: int,
    liquidity_mode: str,
) -> dict[str, Any]:
    factor_family = factor_family.strip()
    grid_args = _grid_args(
        factor_family=factor_family,
        product_groups=product_groups,
        params=params,
        f_values=f_values,
        rev=rev,
        top=top,
    )
    commands: list[dict[str, str]] = [
        {
            "phase": "setup",
            "title": "选择因子家族上下文",
            "command": "factortester single_factor_test --factor-family " + shlex.quote(factor_family),
        },
        {
            "phase": "setup",
            "title": "查看 FactorExpr 可用算子",
            "command": "factortester custom_factors operators",
        },
        {
            "phase": "setup",
            "title": "准备并同步因子工作区",
            "command": "factortester custom_factors workspace build && factortester custom_factors workspace sync",
        },
    ]
    if template:
        commands.append(
            {
                "phase": "setup",
                "title": "加载单因子测试模板",
                "command": "factortester single_factor_test --factor-family "
                + shlex.quote(factor_family)
                + " template load "
                + shlex.quote(template),
            }
        )
        commands.append(
            {
                "phase": "setup",
                "title": "同步模板到独立回测草稿",
                "command": "factortester backtest template --from-module-template single_factor_test load "
                + shlex.quote(template),
            }
        )
    commands.extend(
        [
            {
                "phase": "ic_test",
                "title": "IC/IR 预筛选",
                "command": "factortester ic_test grid " + " ".join(grid_args),
            },
            {
                "phase": "factor_type_analysis",
                "title": "因子类型分析",
                "command": "factortester factor_type_analysis grid " + " ".join(grid_args),
            },
            {
                "phase": "backtest_grid",
                "title": "分组回测参数网格",
                "command": "factortester backtest compare factor-grid "
                + " ".join([*grid_args, "--volume-capacity-mode", shlex.quote(liquidity_mode)]),
            },
            {
                "phase": "results_audit",
                "title": "查看回测摘要",
                "command": "factortester backtest results summary",
            },
            {
                "phase": "results_audit",
                "title": "导出订单流",
                "command": "factortester backtest results order-flow --output order_flow.csv",
            },
        ]
    )
    return {
        "factor_family": factor_family,
        "steps": commands,
        "validation_checklist": _validation_checklist(),
        "notes": [
            "这是把现有 CLI 映射到行业因子研究流程的步骤清单，不是一键执行命令。",
            "先跑 IC/类型/序列诊断，再跑含成本和容量的回测网格。",
            "所有命令都通过 HTTP 操作服务端，不依赖用户本机有服务端源码。",
        ],
    }


def _grid_args(
    *,
    factor_family: str,
    product_groups: tuple[str, ...],
    params: tuple[str, ...],
    f_values: tuple[str, ...],
    rev: bool,
    top: int,
) -> list[str]:
    args: list[str] = ["--factor-family", shlex.quote(factor_family)]
    for item in product_groups:
        args.extend(["--product-group", shlex.quote(item)])
    for item in params or ("N=2m",):
        args.extend(["--param", shlex.quote(item)])
    for item in f_values or ("1m",):
        args.extend(["--f", shlex.quote(item)])
    args.append("--rev" if rev else "--no-rev")
    args.extend(["--top", str(top)])
    return args


def _validation_checklist() -> list[dict[str, str]]:
    return [
        {"gate": "因子定义", "requirement": "写清因子家族、参数、方向、产品域和时间范围。"},
        {"gate": "样本域", "requirement": "产品路径候选必须点时一致；网格可以同时扫参数和产品组。"},
        {"gate": "无未来函数", "requirement": "信号使用可见数据；默认下一 bar open 成交；close 信号不得同 bar 成交。"},
        {"gate": "IC/IR", "requirement": "至少检查 RankIC、ICIR、样本数、滚动稳定性和 IC 衰减。"},
        {"gate": "类型分析", "requirement": "检查趋势/波动率等参照类型相关性，以及产品组内相关性来源。"},
        {"gate": "多重检验", "requirement": "参数/产品组网格越大，越要报告候选数量和样本外验证。"},
        {"gate": "交易成本", "requirement": "费率、滑点、成交量容量和换手率必须进入回测解释。"},
        {"gate": "容量", "requirement": "成交量容量限制与不限制至少做一次对照。"},
        {"gate": "结果核查", "requirement": "保存统计、净值、订单流、snapshot；异常跳变要定位到 flow 或数据。"},
    ]
