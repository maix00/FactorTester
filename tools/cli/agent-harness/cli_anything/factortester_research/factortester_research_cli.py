from __future__ import annotations

import json
import shlex
from pathlib import Path

import click

from . import __version__
from .core.plan import build_factor_research_plan, validation_checklist
from .core.external_factor import (
    validate_dataset_manifest,
    validate_factor_manifest,
    validate_handoff_manifest,
    vibe_pipeline_plan,
)
from .core.session import (
    DEFAULT_SESSION,
    load_session,
    mark_factor_improvement_required,
    record_event,
    record_gap,
    resolve_gap,
    save_session,
)
from .core.service import fetch_worktrees, restart_worktree_service
from .core.slices import default_factor_validation_plan
from .core.workspace import inspect_factor_source, parse_workspace_root
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
        skin.status("factor_families", ", ".join(session.factor_families) or "未设置")
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
@click.option("--factor-family", "factor_families", multiple=True, required=True, help="因子家族 alias，可重复。")
@click.option("--factor", "factors", multiple=True, help="具体 factor，格式 FAMILY_ALIAS=FACTOR_ALIAS，可重复。")
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
    session.configuration_file = configuration_file
    session.plan = build_factor_research_plan(
        factor_families=list(factor_families),
        factors=list(factors),
        configuration_file=configuration_file,
        analyses=list(analyses) or None,
    )
    record_event(
        session, "plan_created", factor_families=list(factor_families),
        factors=list(factors), configuration_file=configuration_file,
    )
    payload = {"session": session.to_dict(), "validation_checklist": validation_checklist()}
    if not dry_run:
        save_session(session, session_path)
    if as_json:
        _echo_json(payload)
        return
    click.echo(f"研究计划: {', '.join(factor_families)}")
    for index, item in enumerate(session.plan, start=1):
        click.echo(f"{index}. [{item['phase']}] {item['purpose']}")
        click.echo(f"   {item['command']}")


@cli.command("slice-plan")
@click.option("--in-sample-start", default="2024-01-01", show_default=True)
@click.option("--in-sample-end", default="2025-12-31", show_default=True)
@click.option("--oos-start", default="2026-01-01", show_default=True)
@click.option("--oos-end", default="2026-12-31", show_default=True)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def slice_plan(
    in_sample_start: str,
    in_sample_end: str,
    oos_start: str,
    oos_end: str,
    as_json: bool,
) -> None:
    """Print the standard factor-research time-slice validation plan."""
    plan = default_factor_validation_plan(
        in_sample_start=in_sample_start,
        in_sample_end=in_sample_end,
        oos_start=oos_start,
        oos_end=oos_end,
    )
    payload = plan.to_dict()
    if as_json:
        _echo_json(payload)
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
        raise click.ClickException("run-step 后需要 factortester 参数，例如: run-step -- job list")
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
        if session.operator_mode == "source_owner":
            click.echo("状态: code_improvement_required；请修复平台代码、运行测试，并用 service restart 经 7998 重启后继续。")
        else:
            click.echo("状态: code_improvement_required；当前 operator_mode=client_only，不能修改服务器源码，请导出 gap 证据交给维护者。")


@cli.group("operator")
def operator() -> None:
    """Configure whether this agent can modify FactorTester server source."""


@operator.command("set")
@click.option("--mode", type=click.Choice(["client_only", "source_owner"]), required=True, help="client_only 只能使用远端服务；source_owner 可以修改并重启服务器代码。")
@click.option("--admin-port", default=7998, show_default=True, type=int, help="本机 worktree Flask manager 管理端口。")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def operator_set(ctx: click.Context, mode: str, admin_port: int, as_json: bool) -> None:
    """Persist source-code ownership and admin-port assumptions."""
    session = load_session(ctx.obj["session_path"])
    session.operator_mode = mode
    session.admin_port = admin_port
    record_event(session, "operator_configured", operator_mode=mode, admin_port=admin_port)
    save_session(session, ctx.obj["session_path"])
    if as_json:
        _echo_json({"session": session.to_dict()})
        return
    click.echo(f"operator_mode: {mode}")
    click.echo(f"admin_port: {admin_port}")
    if mode == "client_only":
        click.echo("说明: 当前用户没有服务器源码，平台代码缺口只能记录并交给维护者；仍可通过因子 workspace 修改可写因子。")
    else:
        click.echo("说明: 平台代码修复后，使用 `service restart` 通过管理端口重启目标服务。")


@cli.group("service")
def service() -> None:
    """Use the local 7998 worktree manager for source-owner validation loops."""


@service.command("list")
@click.option("--admin-port", default=None, type=int, help="覆盖 session 中的管理端口。")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def service_list(ctx: click.Context, admin_port: int | None, as_json: bool) -> None:
    """List worktrees exposed by the local Flask manager."""
    session = load_session(ctx.obj["session_path"])
    port = admin_port or session.admin_port
    try:
        rows = [item.__dict__ for item in fetch_worktrees(admin_port=port)]
    except Exception as exc:
        raise click.ClickException(f"无法访问管理端口 {port}: {exc}") from exc
    if as_json:
        _echo_json({"admin_port": port, "worktrees": rows})
        return
    for item in rows:
        click.echo(f"{item['branch']} port={item['port']} running={item['running']} path={item['path']}")


@service.command("restart")
@click.option("--target-port", default=0, type=int, help="要重启的服务端口，例如 8123。")
@click.option("--branch", default="", help="按 worktree branch/label 选择目标。")
@click.option("--path", "target_path", default="", help="按 worktree path 选择目标。")
@click.option("--admin-port", default=None, type=int, help="覆盖 session 中的管理端口。")
@click.option("--dry-run", is_flag=True, help="只解析并打印 stop/start 动作。")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def service_restart(
    ctx: click.Context,
    target_port: int,
    branch: str,
    target_path: str,
    admin_port: int | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Restart a managed FactorTester server after source-code fixes."""
    session = load_session(ctx.obj["session_path"])
    if session.operator_mode != "source_owner":
        raise click.ClickException("当前 operator_mode=client_only：没有服务器源码的用户不能修改代码或重启服务。请先用 `operator set --mode source_owner`。")
    port = admin_port or session.admin_port
    if not any([target_port, branch, target_path]):
        raise click.ClickException("必须指定 --target-port、--branch 或 --path 之一，避免重启错服务。")
    try:
        payload = restart_worktree_service(
            admin_port=port,
            target_port=target_port,
            branch=branch,
            path=target_path,
            dry_run=dry_run,
        )
    except Exception as exc:
        raise click.ClickException(f"重启失败: {exc}") from exc
    record_event(session, "service_restart", admin_port=port, target=payload["target"], dry_run=dry_run)
    save_session(session, ctx.obj["session_path"])
    if as_json:
        _echo_json(payload)
        return
    click.echo(f"target: {payload['target']['branch']} port={payload['target']['port']}")
    for action in payload["actions"]:
        click.echo(f"- {action['action']} {action['path']} port={action['port']}")
    if dry_run:
        click.echo("dry-run: 未执行 stop/start")
    else:
        click.echo("已通过管理端口提交 stop/start；请重新运行失败步骤验证。")


@cli.group("workspace")
def workspace() -> None:
    """Prepare and inspect the FactorTester factor workspace."""


@workspace.command("prepare")
@click.option("--build", "do_build", is_flag=True, help="先执行 workspace build。")
@click.option("--sync/--no-sync", default=True, show_default=True, help="从数据库同步 workspace。")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def workspace_prepare(ctx: click.Context, do_build: bool, sync: bool, as_json: bool) -> None:
    """Prepare local factor workspace through the real factortester CLI."""
    session_path = ctx.obj["session_path"]
    session = load_session(session_path)
    commands: list[list[str]] = []
    if do_build:
        commands.append(["custom_factors", "workspace", "build"])
    if sync:
        commands.append(["custom_factors", "workspace", "sync"])
    commands.extend(
        [
            ["custom_factors", "workspace", "show"],
            ["custom_factors", "workspace", "git", "status"],
        ]
    )
    results = []
    root = ""
    for args in commands:
        result = run_factortester(args, timeout=600)
        results.append(result.as_dict())
        if result.returncode != 0:
            record_gap(session, "Factor workspace command failed", result.stderr or result.stdout, command=result.argv)
            break
        root = root or parse_workspace_root(result.stdout)
    if root:
        session.factor_source["workspace_root"] = root
    record_event(session, "workspace_prepared", root=root, command_count=len(results))
    save_session(session, session_path)
    payload = {"workspace_root": root, "results": results, "session": session.to_dict()}
    if as_json:
        _echo_json(payload)
        return
    if root:
        click.echo(f"workspace: {root}")
    for item in results:
        click.echo("$ " + " ".join(shlex.quote(part) for part in item["argv"]))
        if item.get("stdout"):
            click.echo(str(item["stdout"]).rstrip())
        if item.get("stderr"):
            click.echo(str(item["stderr"]).rstrip(), err=True)


@workspace.command("inspect")
@click.option("--factor-family", required=True, help="因子家族名。")
@click.option("--root", default="", help="显式指定 workspace root；默认从 session 或 factortester workspace show 解析。")
@click.option("--sync/--no-sync", default=True, show_default=True, help="inspect 前先同步 workspace。")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def workspace_inspect(ctx: click.Context, factor_family: str, root: str, sync: bool, as_json: bool) -> None:
    """Inspect local factor source before testing a factor family."""
    session_path = ctx.obj["session_path"]
    session = load_session(session_path)
    workspace_root = root or str(session.factor_source.get("workspace_root") or "")
    if sync:
        sync_result = run_factortester(["custom_factors", "workspace", "sync"], timeout=600)
        record_event(session, "workspace_sync_before_inspect", returncode=sync_result.returncode)
        if sync_result.returncode != 0:
            record_gap(session, "Factor workspace sync failed", sync_result.stderr or sync_result.stdout, command=sync_result.argv)
            save_session(session, session_path)
            raise click.ClickException(sync_result.stderr or sync_result.stdout)
        workspace_root = workspace_root or parse_workspace_root(sync_result.stdout)
    if not workspace_root:
        show_result = run_factortester(["custom_factors", "workspace", "show"], timeout=60)
        if show_result.returncode != 0:
            record_gap(session, "Factor workspace root unavailable", show_result.stderr or show_result.stdout, command=show_result.argv)
            save_session(session, session_path)
            raise click.ClickException(show_result.stderr or show_result.stdout)
        workspace_root = parse_workspace_root(show_result.stdout)
    if not workspace_root:
        record_gap(session, "Factor workspace root unavailable", "factortester workspace show did not expose a parseable root")
        save_session(session, session_path)
        raise click.ClickException("无法解析 factor workspace root")
    report = inspect_factor_source(workspace_root, factor_family)
    describe_result = run_factortester(
        ["custom_factors", "describe", factor_family, "--source-code", "--json"],
        timeout=120,
    )
    if describe_result.returncode != 0:
        record_gap(session, "Factor operator tree unavailable", describe_result.stderr or describe_result.stdout, command=describe_result.argv)
        save_session(session, session_path)
        raise click.ClickException(describe_result.stderr or describe_result.stdout)
    try:
        import json

        factor_tree = json.loads(describe_result.stdout or "{}")
    except Exception as exc:
        record_gap(session, "Factor operator tree invalid", f"{type(exc).__name__}: {exc}", command=describe_result.argv)
        save_session(session, session_path)
        raise click.ClickException("无法解析因子算子树 JSON") from exc
    source_checks = factor_tree.get("source_checks") or {}
    report["tree_repr"] = factor_tree.get("tree_repr") or ""
    report["operator_keys"] = factor_tree.get("operator_keys") or []
    report["source_checks"] = source_checks
    if factor_family not in session.factor_families:
        session.factor_families.append(factor_family)
    session.factor_source = report
    record_event(session, "factor_source_inspected", factor_family=factor_family, file_count=report["file_count"])
    if report["file_count"] == 0:
        record_gap(session, "Factor source not found in workspace", f"factor_family={factor_family}, root={workspace_root}")
    if source_checks and not source_checks.get("ok"):
        record_gap(
            session,
            "Factor source and operator tree mismatch",
            f"missing_in_tree={source_checks.get('missing_in_tree')}, factor_family={factor_family}",
            command=describe_result.argv,
        )
        save_session(session, session_path)
        raise click.ClickException("因子源码与后端解析算子树不一致，请先修复因子源码或 FactorExpr 算子语义")
    save_session(session, session_path)
    if as_json:
        _echo_json({"factor_source": report, "session": session.to_dict()})
        return
    click.echo(f"因子源码: {factor_family}")
    click.echo(f"workspace: {workspace_root}")
    if not report["files"]:
        click.echo("未找到匹配源码")
        return
    for item in report["files"]:
        click.echo(f"- {item['relative_path']}")
        for line in item["summary"][:16]:
            click.echo(f"    {line}")
    if report.get("operator_keys"):
        click.echo("算子: " + ", ".join(str(key) for key in report["operator_keys"]))


@cli.group("decision")
def decision() -> None:
    """Record research decisions that alter the workflow state."""


@decision.command("poor-result")
@click.option("--reason", required=True, help="为什么认为表现不好。")
@click.option("--evidence", default="", help="可选 JSON 或文本证据。")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def decision_poor_result(ctx: click.Context, reason: str, evidence: str, as_json: bool) -> None:
    """Mark research as needing factor-workspace improvement."""
    session = load_session(ctx.obj["session_path"])
    evidence_payload: dict[str, object] = {}
    if evidence:
        try:
            parsed = json.loads(evidence)
            evidence_payload = parsed if isinstance(parsed, dict) else {"value": parsed}
        except Exception:
            evidence_payload = {"text": evidence}
    row = mark_factor_improvement_required(session, reason, evidence=evidence_payload)
    save_session(session, ctx.obj["session_path"])
    if as_json:
        _echo_json({"decision": row, "session": session.to_dict()})
        return
    click.echo("状态: factor_improvement_required")
    click.echo("下一步:")
    click.echo("  factortester custom_factors workspace git diff")
    click.echo("  编辑 workspace 中的因子源码/参数")
    click.echo("  factortester custom_factors workspace push")
    click.echo("  重新运行 workspace inspect、IC、类型分析和回测")


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
    click.echo(f"operator_mode: {session.operator_mode}")
    click.echo(f"admin_port: {session.admin_port}")
    click.echo(f"factor_families: {', '.join(session.factor_families) or '未设置'}")
    click.echo(f"factors: {', '.join(session.factors) or '未设置'}")
    click.echo(f"configuration_file: {session.configuration_file or '无'}")
    click.echo(f"plan_steps: {len(session.plan)}")
    click.echo(f"open_gaps: {sum(1 for item in session.gaps if item.get('status') == 'open')}")
    source = session.factor_source or {}
    if source:
        click.echo(f"factor_source_files: {source.get('file_count', 0)}")
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


@cli.group("external-factor")
def external_factor() -> None:
    """Plan and validate external Vibe factor artifacts without bypassing GTHT."""


@external_factor.command("plan")
@click.option("--integration-root", required=True, type=click.Path(file_okay=False))
@click.option("--data-root", required=True, type=click.Path(file_okay=False))
@click.option("--alpha", "alpha_id", required=True)
@click.option("--dataset-version", default="v1", show_default=True)
@click.option("--json", "as_json", is_flag=True)
def external_factor_plan(
    integration_root: str, data_root: str, alpha_id: str,
    dataset_version: str, as_json: bool,
) -> None:
    """Print the reproducible daily/minute panel and Vibe factor pipeline."""
    payload = vibe_pipeline_plan(
        integration_root=integration_root, data_root=data_root,
        alpha_id=alpha_id, dataset_version=dataset_version,
    )
    if as_json:
        _echo_json({"steps": payload})
        return
    for index, item in enumerate(payload, start=1):
        click.echo(f"{index}. {item['phase']}")
        if item.get("argv"):
            click.echo("   " + " ".join(shlex.quote(part) for part in item["argv"]))
        if item.get("reason"):
            click.echo(f"   {item['reason']}")


@external_factor.command("validate")
@click.option("--dataset-manifest", multiple=True, type=click.Path(dir_okay=False))
@click.option("--factor-manifest", multiple=True, type=click.Path(dir_okay=False))
@click.option("--handoff-manifest", multiple=True, type=click.Path(dir_okay=False))
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def external_factor_validate(
    ctx: click.Context, dataset_manifest: tuple[str, ...],
    factor_manifest: tuple[str, ...], handoff_manifest: tuple[str, ...],
    as_json: bool,
) -> None:
    """Validate provenance, non-empty output, and next-bar timing contracts."""
    if not dataset_manifest and not factor_manifest and not handoff_manifest:
        raise click.ClickException("至少指定一个 dataset/factor/handoff manifest")
    try:
        results = [
            *(validate_dataset_manifest(path) for path in dataset_manifest),
            *(validate_factor_manifest(path) for path in factor_manifest),
            *(validate_handoff_manifest(path) for path in handoff_manifest),
        ]
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    session = load_session(ctx.obj["session_path"])
    record_event(session, "external_factor_artifacts_validated", artifacts=results)
    save_session(session, ctx.obj["session_path"])
    if as_json:
        _echo_json({"valid": True, "artifacts": results})
        return
    for item in results:
        click.echo(f"OK {item['kind']}: {item['path']}")


if __name__ == "__main__":
    cli()
