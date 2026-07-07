from __future__ import annotations

import json
import shlex
from pathlib import Path

import click

from . import __version__
from .core.plan import build_factor_research_plan, validation_checklist
from .core.session import (
    DEFAULT_SESSION,
    load_session,
    record_event,
    record_gap,
    resolve_gap,
    save_session,
)
from .utils.factortester_backend import looks_like_platform_gap, resolve_factortester, run_factortester
from .utils.repl_skin import ReplSkin


def _echo_json(payload: object) -> None:
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))


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
        skin.status("factor_family", session.factor_family or "未设置")
        skin.info("Use `plan`, `run-step`, `gap list`, and `status` commands. This harness calls the real `factortester` CLI.")


@cli.command("doctor")
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
        _echo_json(payload)
        return
    for item in checks:
        click.echo(f"{item['name']}: {item['status']} · {item['detail']}")


@cli.command("plan")
@click.option("--factor-family", required=True, help="因子家族名，例如 SgCCS。")
@click.option("--template", default="", help="可选模板名，例如 '2026-06-02 07:20:47'。")
@click.option("--product-group", "product_groups", multiple=True, help="产品组，可重复。")
@click.option("--n", "n_values", multiple=True, help="N 参数候选，可重复。")
@click.option("--f", "f_values", multiple=True, help="$F 参数候选，可重复。")
@click.option("--rev/--no-rev", default=True, show_default=True, help="是否包含 $Rev。")
@click.option("--top", default=12, show_default=True, type=int, help="每组输出 Top N。")
@click.option("--dry-run", is_flag=True, help="只打印，不保存 session。")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def plan(
    ctx: click.Context,
    factor_family: str,
    template: str,
    product_groups: tuple[str, ...],
    n_values: tuple[str, ...],
    f_values: tuple[str, ...],
    rev: bool,
    top: int,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Create a rigorous factor research plan without executing it."""
    session_path = ctx.obj["session_path"]
    session = load_session(session_path)
    session.factor_family = factor_family
    session.template = template
    session.product_groups = list(product_groups)
    session.plan = build_factor_research_plan(
        factor_family=factor_family,
        template=template,
        product_groups=list(product_groups),
        n_values=list(n_values),
        f_values=list(f_values),
        include_rev=rev,
        top=top,
    )
    grid_size = max(len(product_groups), 1) * max(len(n_values), 1) * max(len(f_values), 1) * (1 if rev else 1)
    session.hypotheses_tested += grid_size
    record_event(session, "plan_created", factor_family=factor_family, template=template, hypotheses=grid_size)
    payload = {"session": session.to_dict(), "validation_checklist": validation_checklist()}
    if not dry_run:
        save_session(session, session_path)
    if as_json:
        _echo_json(payload)
        return
    click.echo(f"研究计划: {factor_family}")
    for index, item in enumerate(session.plan, start=1):
        click.echo(f"{index}. [{item['phase']}] {item['purpose']}")
        click.echo(f"   {item['command']}")


@cli.command("run-step", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
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
        raise click.ClickException("run-step 后需要 factortester 参数，例如: run-step -- ic_test grid ...")
    session_path = ctx.obj["session_path"]
    session = load_session(session_path)
    command_text = "factortester " + " ".join(shlex.quote(item) for item in args)
    if dry_run:
        payload = {"dry_run": True, "command": command_text}
        if as_json:
            _echo_json(payload)
        else:
            click.echo(command_text)
        return
    result = run_factortester(args, timeout=timeout)
    record_event(session, "command_run", command=result.argv, returncode=result.returncode)
    if looks_like_platform_gap(result):
        record_gap(session, "FactorTester CLI/backend capability gap", result.stderr or result.stdout, command=result.argv)
    save_session(session, session_path)
    payload = {"result": result.as_dict(), "session": session.to_dict()}
    if as_json:
        _echo_json(payload)
        return
    click.echo(f"{command_text}")
    click.echo(f"returncode={result.returncode}")
    if result.stdout:
        click.echo(result.stdout.rstrip())
    if result.stderr:
        click.echo(result.stderr.rstrip(), err=True)
    if session.status == "code_improvement_required":
        click.echo("状态: code_improvement_required；请先修复平台缺口并验证，再继续研究。")


@cli.group("gap")
def gap() -> None:
    """Manage codebase gaps discovered during research."""


@gap.command("add")
@click.argument("title")
@click.argument("detail", required=False, default="")
@click.pass_context
def gap_add(ctx: click.Context, title: str, detail: str) -> None:
    session = load_session(ctx.obj["session_path"])
    row = record_gap(session, title, detail)
    save_session(session, ctx.obj["session_path"])
    click.echo(f"新增 gap: {row['id']}")


@gap.command("list")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def gap_list(ctx: click.Context, as_json: bool) -> None:
    session = load_session(ctx.obj["session_path"])
    if as_json:
        _echo_json({"gaps": session.gaps, "status": session.status})
        return
    if not session.gaps:
        click.echo("无 gap")
        return
    for item in session.gaps:
        click.echo(f"{item['id']} [{item['status']}] {item['title']}")
        if item.get("detail"):
            click.echo(f"  {item['detail']}")


@gap.command("resolve")
@click.argument("gap_id")
@click.option("--note", default="", help="修复说明。")
@click.pass_context
def gap_resolve(ctx: click.Context, gap_id: str, note: str) -> None:
    session = load_session(ctx.obj["session_path"])
    row = resolve_gap(session, gap_id, note=note)
    record_event(session, "gap_resolved", gap_id=gap_id)
    save_session(session, ctx.obj["session_path"])
    click.echo(f"已解决 gap: {row['id']}")


@cli.command("status")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def status(ctx: click.Context, as_json: bool) -> None:
    """Print current research session state."""
    session = load_session(ctx.obj["session_path"])
    payload = session.to_dict()
    if as_json:
        _echo_json(payload)
        return
    click.echo(f"status: {session.status}")
    click.echo(f"factor_family: {session.factor_family or '未设置'}")
    click.echo(f"template: {session.template or '无'}")
    click.echo(f"product_groups: {', '.join(session.product_groups) if session.product_groups else '无'}")
    click.echo(f"plan_steps: {len(session.plan)}")
    click.echo(f"open_gaps: {sum(1 for item in session.gaps if item.get('status') == 'open')}")
    click.echo(f"hypotheses_tested: {session.hypotheses_tested}")


@cli.command("checklist")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def checklist(as_json: bool) -> None:
    """Print the quantitative validation checklist."""
    items = validation_checklist()
    if as_json:
        _echo_json({"checklist": items})
        return
    for item in items:
        click.echo(f"- {item}")


if __name__ == "__main__":
    cli()
