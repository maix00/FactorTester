"""Plan, execute, and inspect ordinary research steps."""

from __future__ import annotations

import shlex

import click

from ..core.evidence import persist_command_evidence
from ..core.plan import build_factor_research_plan, validation_checklist
from ..core.session import load_session, record_event, record_gap, save_session
from ..core.slices import default_factor_validation_plan
from ..utils.factortester_backend import looks_like_platform_gap, resolve_factortester, run_factortester
from .common import echo_json

@click.command("doctor")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def doctor(as_json: bool) -> None:
    """Check whether the real factortester backend CLI is available."""
    checks = []
    try:
        executable = resolve_factortester()
        checks.append({"name": "factortester", "status": "ok", "detail": executable})
        result = run_factortester(["--help"], timeout=30)
        checks.append({"name": "factortester --help", "status": "ok" if result.returncode == 0 else "fail", "detail": result.stderr or result.stdout[:200]})
    except Exception as exc:
        checks.append({"name": "factortester", "status": "fail", "detail": str(exc)})
    payload = {"success": all(item["status"] == "ok" for item in checks), "checks": checks}
    if as_json:
        echo_json(payload)
        return
    for item in checks:
        click.echo(f"{item['name']}: {item['status']} · {item['detail']}")

@click.command("plan")
@click.option("--factor-family", "factor_families", multiple=True, required=True, help="因子家族 alias，可重复。")
@click.option("--factor", "factors", multiple=True, help="具体 factor，格式 FAMILY_ALIAS=FACTOR_ALIAS，可重复。")
@click.option(
    "--product",
    "products",
    multiple=True,
    required=True,
    help="用户在当前对话确认的研究产品，可重复。",
)
@click.option(
    "--source",
    "sources",
    multiple=True,
    required=True,
    help="用户确认用于该产品范围的数据源，可重复。",
)
@click.option("--configuration-file", required=True, type=click.Path(dir_okay=False), help="canonical ResearchConfiguration JSON。")
@click.option(
    "--analysis", "analyses", multiple=True,
    type=click.Choice(["backtest", "ic", "factor_evaluation", "factor_type_analysis"]),
)
@click.option("--dry-run", is_flag=True, help="只打印，不保存 session。")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def plan(
    ctx: click.Context,
    factor_families: tuple[str, ...],
    factors: tuple[str, ...],
    products: tuple[str, ...],
    sources: tuple[str, ...],
    configuration_file: str,
    analyses: tuple[str, ...],
    dry_run: bool,
    as_json: bool,
) -> None:
    """Create a rigorous factor research plan without executing it."""
    session_path = ctx.obj["session_path"]
    session = load_session(session_path)
    session.factor_families = list(factor_families)
    session.factors = list(factors)
    session.products = list(products)
    session.data_sources = list(sources)
    session.configuration_file = configuration_file
    session.plan = build_factor_research_plan(
        factor_families=list(factor_families),
        factors=list(factors),
        products=list(products),
        sources=list(sources),
        configuration_file=configuration_file,
        analyses=list(analyses) or None,
    )
    record_event(
        session,
        "product_scope_confirmed",
        products=list(products),
        data_sources=list(sources),
        factor_families=list(factor_families),
        factors=list(factors),
        configuration_file=configuration_file,
    )
    payload = {"session": session.to_dict(), "validation_checklist": validation_checklist()}
    if not dry_run:
        save_session(session, session_path)
    if as_json:
        echo_json(payload)
        return
    click.echo(f"研究计划: {', '.join(factor_families)}")
    for index, item in enumerate(session.plan, start=1):
        click.echo(f"{index}. [{item['phase']}] {item['purpose']}")
        click.echo(f"   {item['command']}")
@click.command("slice-plan")
@click.option("--in-sample-start", required=True)
@click.option("--in-sample-end", required=True)
@click.option("--oos-start", required=True)
@click.option("--oos-end", required=True)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def slice_plan(
    in_sample_start: str,
    in_sample_end: str,
    oos_start: str,
    oos_end: str,
    as_json: bool,
) -> None:
    """Print an explicit legacy slice plan; ordinary planning uses TrialPlan."""
    plan = default_factor_validation_plan(
        in_sample_start=in_sample_start,
        in_sample_end=in_sample_end,
        oos_start=oos_start,
        oos_end=oos_end,
    )
    payload = plan.to_dict()
    if as_json:
        echo_json(payload)
        return
    click.echo(f"validation_plan: {payload['name']}")
    click.echo(f"in_sample: {in_sample_start} -> {in_sample_end}")
    click.echo(f"oos_annotation: {oos_start} -> {oos_end}")
    click.echo(f"selection_policy: {payload['selection_policy']}")
    for slice_set in payload["slice_sets"]:
        click.echo(f"\n[{slice_set['name']}] {slice_set['description']}")
        if not slice_set["slices"]:
            click.echo("  (requires data-driven generation artifact)")
            continue
        for item in slice_set["slices"]:
            click.echo(f"  {item['name']}: {item['start']} -> {item['end']} · {item['purpose']} · {item['kind']}")
@click.command("run-step", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.option("--dry-run", is_flag=True, help="打印将执行的 factortester 命令但不运行。")
@click.option("--timeout", default=600, show_default=True, type=int, help="命令超时秒数。")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def run_step(ctx: click.Context, dry_run: bool, timeout: int, as_json: bool) -> None:
    """Run one real factortester command and record research/gap state."""
    args = list(ctx.args)
    if args[:1] == ["--"]:
        args = args[1:]
    if not args:
        raise click.ClickException("run-step 后需要 factortester 参数，例如: run-step -- job list")
    session_path = ctx.obj["session_path"]
    session = load_session(session_path)
    command_text = "factortester " + " ".join(shlex.quote(item) for item in args)
    if dry_run:
        payload = {"dry_run": True, "command": command_text}
        if as_json:
            echo_json(payload)
        else:
            click.echo(command_text)
        return
    result = run_factortester(args, timeout=timeout)
    record_event(session, "command_run", command=result.argv, returncode=result.returncode)
    platform_gap = looks_like_platform_gap(result)
    if platform_gap:
        record_gap(session, "FactorTester CLI/backend capability gap", result.stderr or result.stdout, command=result.argv)
    envelope = persist_command_evidence(
        session_path=session_path,
        envelope_id=f"command-{len(session.evidence_envelopes) + 1}",
        argv=result.argv,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        hypotheses_tested=session.hypotheses_tested,
        stop_condition=(
            "platform_capability_gap" if platform_gap else None
        ),
    )
    session.evidence_envelopes.append(envelope)
    save_session(session, session_path)
    payload = {"result": result.as_dict(), "session": session.to_dict()}
    if as_json:
        echo_json(payload)
        return
    click.echo(f"{command_text}")
    click.echo(f"returncode={result.returncode}")
    if result.stdout:
        click.echo(result.stdout.rstrip())
    if result.stderr:
        click.echo(result.stderr.rstrip(), err=True)
    if session.status == "code_improvement_required":
        if session.operator_mode == "source_owner":
            click.echo("状态: code_improvement_required；请修复平台代码、运行测试，并用 service restart 经 7998 重启后继续。")
        else:
            click.echo("状态: code_improvement_required；当前 operator_mode=client_only，不能修改服务器源码，请导出 gap 证据交给维护者。")
@click.command("checklist")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def checklist(as_json: bool) -> None:
    """Print the quantitative validation checklist."""
    items = validation_checklist()
    if as_json:
        echo_json({"checklist": items})
        return
    for item in items:
        click.echo(f"- {item}")
