"""Research workspace, configuration, template, run, and job commands."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

import click

from tools.cli.core.context import client_from_config, requested_ports
from tools.cli.core.errors import friendly_errors
from tools.cli.state import load_state, save_state
from tools.cli.step import field_occurrences, render_step_event


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _require_workspace():
    state = load_state()
    if not state.workspace_id:
        raise click.ClickException("尚未选择 research workspace；请先运行 factortester workspace create/use")
    return state


@click.group("workspace")
def workspace() -> None:
    """Manage durable research contexts and their active configuration."""


@click.group("external-factor")
def external_factor() -> None:
    """Validate and attach external precomputed factor artifacts."""


@external_factor.command("validate")
@click.argument(
    "manifest_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--attach",
    is_flag=True,
    help="Attach the validated immutable descriptor to the active workspace.",
)
@friendly_errors
def external_factor_validate(manifest_path: Path, attach: bool) -> None:
    client = client_from_config()
    artifact = client.validate_external_factor_artifact(str(manifest_path.resolve()))
    if attach:
        state = _require_workspace()
        configuration = client.get_workspace_configuration(state.workspace_id)
        payload = dict(configuration["payload"])
        shared = dict(payload["shared"])
        artifacts = [
            item for item in shared.get("external_factor_artifacts") or []
            if item.get("artifact_id") != artifact.get("artifact_id")
        ]
        artifacts.append(artifact)
        shared["external_factor_artifacts"] = artifacts
        payload["shared"] = shared
        value = client.update_workspace_configuration(
            state.workspace_id,
            expected_revision=state.configuration_revision,
            payload=payload,
        )
        state.configuration_revision = int(value["revision"])
        save_state(state)
    click.echo(_json({
        "artifact": artifact,
        "attached": attach,
        "workspace_id": load_state().workspace_id if attach else "",
    }))


@workspace.command("create")
@click.option("--factor-family", "factor_families", multiple=True, help="因子家族 alias，可重复。")
@click.option(
    "--factor", "factors", multiple=True,
    help="具体 factor，格式 FAMILY_ALIAS=FACTOR_ALIAS，可重复。",
)
@click.option("--title", default="Factor research", show_default=True)
@friendly_errors
def workspace_create(
    factor_families: tuple[str, ...], factors: tuple[str, ...], title: str,
) -> None:
    families = [{"alias": value} for value in factor_families]
    family_aliases = {item["alias"] for item in families}
    factor_rows = []
    for raw in factors:
        if "=" not in raw:
            raise click.ClickException("--factor 格式必须为 FAMILY_ALIAS=FACTOR_ALIAS")
        family_alias, factor_alias = raw.split("=", 1)
        family_alias = family_alias.strip()
        factor_alias = factor_alias.strip()
        if not family_alias or not factor_alias:
            raise click.ClickException("--factor 格式必须为 FAMILY_ALIAS=FACTOR_ALIAS")
        if family_alias not in family_aliases:
            families.append({"alias": family_alias})
            family_aliases.add(family_alias)
        factor_rows.append({"factor_family_alias": family_alias, "alias": factor_alias})
    value = client_from_config().create_workspace(
        factor_families=families,
        factors=factor_rows,
        title=title,
    )
    state = load_state()
    state.workspace_id = str(value["workspace_id"])
    state.configuration_revision = int(value["configuration"]["revision"])
    save_state(state)
    click.echo(
        f"workspace_id={state.workspace_id} "
        f"configuration_revision={state.configuration_revision}"
    )


@workspace.command("list")
@friendly_errors
def workspace_list() -> None:
    for item in client_from_config().list_workspaces():
        config = item.get("configuration") or {}
        click.echo(
            f"{item.get('workspace_id')} config_revision={config.get('revision')} "
            f"title={item.get('title') or '-'}"
        )


@workspace.command("use")
@click.argument("workspace_id")
@friendly_errors
def workspace_use(workspace_id: str) -> None:
    value = client_from_config().get_workspace(workspace_id)
    state = load_state()
    state.workspace_id = workspace_id
    state.configuration_revision = int((value.get("configuration") or {})["revision"])
    save_state(state)
    click.echo(
        f"workspace_id={workspace_id} "
        f"configuration_revision={state.configuration_revision}"
    )


@workspace.command("show")
@friendly_errors
def workspace_show() -> None:
    state = _require_workspace()
    click.echo(_json(client_from_config().get_workspace(state.workspace_id)))


@workspace.command("update")
@click.option("--file", "configuration_file", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@friendly_errors
def workspace_update(configuration_file: Path) -> None:
    state = _require_workspace()
    payload = json.loads(configuration_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise click.ClickException("configuration JSON must be an object")
    value = client_from_config().update_workspace_configuration(
        state.workspace_id,
        expected_revision=state.configuration_revision,
        payload=payload,
    )
    state.configuration_revision = int(value["revision"])
    save_state(state)
    click.echo(
        f"workspace_id={state.workspace_id} "
        f"configuration_revision={state.configuration_revision}"
    )


@workspace.command("templates")
@friendly_errors
def workspace_templates() -> None:
    for item in client_from_config().list_configuration_templates():
        click.echo(
            f"{item.get('configuration_id')} revision={item.get('revision')} "
            f"name={item.get('name') or '-'}"
        )


@workspace.command("save-template")
@click.argument("name")
@friendly_errors
def workspace_save_template(name: str) -> None:
    state = _require_workspace()
    value = client_from_config().save_configuration_template(state.workspace_id, name=name)
    click.echo(
        f"configuration_id={value.get('configuration_id')} name={value.get('name')} "
        f"source_workspace_id={state.workspace_id}"
    )


@workspace.command("load-template")
@click.argument("configuration_id")
@friendly_errors
def workspace_load_template(configuration_id: str) -> None:
    state = _require_workspace()
    value = client_from_config().load_configuration_template(
        state.workspace_id,
        expected_revision=state.configuration_revision,
        configuration_id=configuration_id,
    )
    state.configuration_revision = int(value["revision"])
    save_state(state)
    click.echo(
        f"workspace_id={state.workspace_id} "
        f"configuration_revision={state.configuration_revision} "
        f"loaded_from={configuration_id}"
    )


@workspace.command("snapshot-create")
@click.argument("name")
@click.option("--source-workspace-id", required=True)
@click.option("--source-configuration-id", required=True)
@click.option("--source-revision", required=True, type=click.IntRange(min=1))
@friendly_errors
def workspace_snapshot_create(
    name: str,
    source_workspace_id: str,
    source_configuration_id: str,
    source_revision: int,
) -> None:
    state = _require_workspace()
    value = client_from_config().create_configuration_snapshot(
        state.workspace_id,
        source_workspace_id=source_workspace_id,
        source_configuration_id=source_configuration_id,
        source_configuration_revision=source_revision,
        name=name,
    )
    click.echo(_json(value))


@workspace.command("snapshot-list")
@friendly_errors
def workspace_snapshot_list() -> None:
    state = _require_workspace()
    click.echo(_json(
        client_from_config().list_configuration_snapshots(
            state.workspace_id
        )
    ))


@click.group("run")
@click.option("--port", "run_ports", multiple=True, type=click.IntRange(1, 65535), help="提交到指定 FactorTester 端口。")
def run(run_ports: tuple[int, ...]) -> None:
    """Submit and inspect immutable research runs."""


@run.command("preview")
@click.option("--analysis", "analyses", multiple=True, type=click.Choice([
    "backtest", "ic", "factor_evaluation", "factor_type_analysis",
]), required=True)
@click.option("--retain-full", is_flag=True, help="预览完整结果保留模式。")
@click.option("--output", "output_requests", multiple=True, help="预先生成的 Job 输出名，可重复；先用 job output-capabilities 查看。")
@click.option("--configuration-snapshot-id", default="")
@click.option(
    "--configuration-snapshot-revision",
    type=click.IntRange(min=1),
)
@click.option(
    "--step",
    "step_mode",
    is_flag=True,
    help="预览逐 flow backtest 模式。",
)
@friendly_errors
def run_preview(
    analyses: tuple[str, ...],
    retain_full: bool,
    output_requests: tuple[str, ...],
    configuration_snapshot_id: str,
    configuration_snapshot_revision: int | None,
    step_mode: bool,
) -> None:
    """Preview the exact frozen RunSpec identity without creating state."""
    state = _require_workspace()
    snapshot_options = (
        {
            "configuration_snapshot_id": configuration_snapshot_id,
            "configuration_snapshot_revision": (
                configuration_snapshot_revision
            ),
        }
        if configuration_snapshot_id
        else {}
    )
    preview_kwargs = {
        "analyses": list(analyses),
        "retention_mode": "full" if retain_full else "summary",
        "step_mode": step_mode,
        **snapshot_options,
    }
    if output_requests:
        preview_kwargs["output_requests"] = list(output_requests)
    result = client_from_config().preview_run(
        state.workspace_id,
        None if configuration_snapshot_id else state.configuration_revision,
        **preview_kwargs,
    )
    click.echo(_json(result))


@run.command("submit")
@click.option("--analysis", "analyses", multiple=True, type=click.Choice([
    "backtest", "ic", "factor_evaluation", "factor_type_analysis",
]), required=True)
@click.option("--retain-full", is_flag=True, help="在服务器配额内保留完整曲线和明细。")
@click.option("--output", "output_requests", multiple=True, help="预先生成的 Job 输出名，可重复；先用 job output-capabilities 查看。")
@click.option("--configuration-snapshot-id", default="")
@click.option(
    "--configuration-snapshot-revision",
    type=click.IntRange(min=1),
)
@click.option("--step", "step_mode", is_flag=True, help="逐 flow 暂停，仅支持单个 backtest。")
@click.option(
    "--trial-binding-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="绑定当前 Hypothesis Branch 已冻结 TrialPlan 的 JSON 文件。",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="输出 RunSpec 报告投影、运行与 Job 的完整机器可读响应。",
)
@friendly_errors
def run_submit(
    analyses: tuple[str, ...],
    retain_full: bool,
    output_requests: tuple[str, ...],
    configuration_snapshot_id: str,
    configuration_snapshot_revision: int | None,
    step_mode: bool,
    trial_binding_file: Path | None,
    as_json: bool,
) -> None:
    state = _require_workspace()
    trial_binding = None
    if trial_binding_file is not None:
        trial_binding = json.loads(
            trial_binding_file.read_text(encoding="utf-8")
        )
        if not isinstance(trial_binding, dict):
            raise click.ClickException(
                "trial binding JSON must be an object"
            )
    snapshot_options = (
        {
            "configuration_snapshot_id": configuration_snapshot_id,
            "configuration_snapshot_revision": (
                configuration_snapshot_revision
            ),
        }
        if configuration_snapshot_id
        else {}
    )
    submit_kwargs = {
        "analyses": list(analyses),
        "retention_mode": "full" if retain_full else "summary",
        "step_mode": step_mode,
        "trial_binding": trial_binding,
        **snapshot_options,
    }
    if output_requests:
        submit_kwargs["output_requests"] = list(output_requests)
    result = client_from_config().submit_run(
        state.workspace_id,
        None if configuration_snapshot_id else state.configuration_revision,
        **submit_kwargs,
    )
    if as_json:
        click.echo(_json(result))
        return
    click.echo(f"run_id={result.get('run_id')}")
    for item in result.get("jobs") or []:
        click.echo(f"job_id={item.get('job_id')} kind={item.get('kind')} status={item.get('status')}")


@run.command("show")
@click.argument("run_id")
@friendly_errors
def run_show(run_id: str) -> None:
    click.echo(_json(client_from_config().get_run(run_id)))


@run.command("clone-workspace")
@click.argument("run_id")
@click.option("--title", default="", help="新工作区标题。")
@friendly_errors
def run_clone_workspace(run_id: str, title: str) -> None:
    workspace = client_from_config().clone_run_workspace(run_id, title=title)
    state = load_state()
    state.workspace_id = str(workspace["workspace_id"])
    state.configuration_revision = int(workspace["configuration"]["revision"])
    save_state(state)
    click.echo(
        f"workspace_id={state.workspace_id} "
        f"configuration_revision={state.configuration_revision} source_run_id={run_id}"
    )


@click.group("job")
@click.option("--port", "job_ports", multiple=True, type=click.IntRange(1, 65535), help="操作指定 FactorTester 端口的任务。")
def job(job_ports: tuple[int, ...]) -> None:
    """Observe and control durable job attempts."""


@job.command("list")
@click.option("--all-workspaces", is_flag=True)
@click.option("--kind", type=click.Choice([
    "backtest", "ic", "factor_evaluation", "factor_type_analysis",
    ]))
@click.option("--status", "statuses", multiple=True, type=click.Choice([
    "submitted", "planning", "awaiting_confirmation", "queued", "running",
    "paused", "succeeded", "failed", "cancelled",
]))
@click.option("--limit", default=20, show_default=True, type=click.IntRange(1, 200))
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def job_list(
    all_workspaces: bool, kind: str | None, statuses: tuple[str, ...], limit: int,
    as_json: bool,
) -> None:
    state = load_state()
    workspace_id = "" if all_workspaces else state.workspace_id
    ports = requested_ports() or (None,)
    rows = []
    for port in ports:
        client = client_from_config() if port is None else client_from_config(port=port)
        kwargs = {
            "workspace_id": workspace_id,
            "status": ",".join(statuses),
            "kind": kind or "",
            "limit": limit,
        }
        if port is not None:
            kwargs["all_ports"] = False
        rows.extend(client.list_jobs(**kwargs))
    rows.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
    rows = rows[:limit * len(ports)]
    if as_json:
        click.echo(_json({"jobs": rows, "count": len(rows)}))
        return
    for item in rows:
        click.echo(
            f"{item.get('job_id')} run={item.get('run_id')} kind={item.get('kind')} "
            f"status={item.get('status')} attempt={item.get('attempt')} "
            f"port={item.get('port') or (item.get('server_context') or {}).get('port') or '-'}"
        )


@job.command("ports")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def job_ports(as_json: bool) -> None:
    """列出 manager 发现的 FactorTester 任务端口。"""
    ports = client_from_config().list_job_ports()
    if as_json:
        click.echo(_json({"ports": ports, "count": len(ports)}))
        return
    click.echo("、".join(str(port) for port in ports) if ports else "暂无可用任务端口")


@job.command("status")
@click.argument("job_id")
@friendly_errors
def job_status(job_id: str) -> None:
    click.echo(_json(client_from_config().get_job(job_id)))


@job.command("config")
@click.argument("job_id")
@friendly_errors
def job_config(job_id: str) -> None:
    """Print the immutable configuration and output declaration for a Job."""
    detail = client_from_config().get_job(job_id)
    click.echo(_json({
        "job_id": job_id,
        "run_id": detail.get("run_id"),
        "kind": detail.get("kind"),
        "run_spec_hash": detail.get("run_spec_hash"),
        "output_requests": detail.get("output_requests") or [],
        "server_context": detail.get("server_context") or {},
        "submission_context": detail.get("submission_context") or {},
        "research_binding": detail.get("research_binding") or {},
        "configuration": detail.get("configuration"),
    }))


@job.command("result")
@click.argument("job_id")
@friendly_errors
def job_result(job_id: str) -> None:
    """Read the retained result, cancellation detail, or failure traceback."""
    click.echo(_json(client_from_config().job_result(job_id)))


@job.command("watch")
@click.argument("job_id")
@click.option("--after", default=0, type=int)
@click.option("--json", "as_json", is_flag=True, help="原样输出完整 SSE 事件 JSON。")
@friendly_errors
def job_watch(job_id: str, after: int, as_json: bool) -> None:
    for event in client_from_config().stream_job_id(job_id, after=after):
        if as_json or event.get("event") != "step" or not isinstance(event.get("data"), dict):
            click.echo(_json(event))
            continue
        for line in render_step_event(event["data"]):
            click.echo(line, color=True)


@job.command("progress")
@click.argument("job_id")
@click.option("--after", default=0, type=int)
@friendly_errors
def job_progress(job_id: str, after: int) -> None:
    """Stream compact progress; this is the one live HTTP/SSE operation."""
    for event in client_from_config().stream_job_id(job_id, after=after):
        if event.get("event") not in {"status", "progress", "signal_progress", "activity", "plan", "result", "error", "heartbeat"}:
            continue
        click.echo(_json(event))


@job.command("step-field")
@click.argument("job_id")
@click.argument("qualified_field")
@click.option("--after", default=0, type=int, help="从指定 SSE 序号之后开始读取。")
@friendly_errors
def job_step_field(job_id: str, qualified_field: str, after: int) -> None:
    """打印下一个 step 中指定全限定字段的完整序列化记录。"""
    for event in client_from_config().stream_job_id(job_id, after=after):
        if event.get("event") != "step" or not isinstance(event.get("data"), dict):
            continue
        occurrences = field_occurrences(event["data"], qualified_field)
        if not occurrences:
            continue
        click.echo(_json({
            "job_id": job_id,
            "field": qualified_field,
            "step": {
                "timestamp": event["data"].get("timestamp"),
                "flow_id": event["data"].get("flow_id"),
                "flow_phase": event["data"].get("flow_phase"),
            },
            "occurrences": occurrences,
        }))
        return
    raise click.ClickException(f"流已结束，未找到字段 {qualified_field!r}")


@job.command("cancel")
@click.argument("job_id")
@friendly_errors
def job_cancel(job_id: str) -> None:
    click.echo(_json(client_from_config().cancel_job(job_id)))


@job.command("retry")
@click.argument("job_id")
@friendly_errors
def job_retry(job_id: str) -> None:
    click.echo(_json(client_from_config().retry_job(job_id)))


@job.command("approve")
@click.argument("job_id")
@friendly_errors
def job_approve(job_id: str) -> None:
    click.echo(_json(client_from_config().approve_job(job_id)))


@job.command("pin")
@click.argument("job_id")
@friendly_errors
def job_pin(job_id: str) -> None:
    click.echo(_json(client_from_config().pin_job(job_id)))


@job.command("unpin")
@friendly_errors
def job_unpin() -> None:
    click.echo(_json(client_from_config().unpin_job()))


@job.command("continue")
@click.argument("job_id")
@click.option("--until", default="", help="Replay until this timestamp, then pause.")
@click.option("--end", "run_to_end", is_flag=True, help="Run the remaining backtest without pausing.")
@click.option("--json", "as_json", is_flag=True, help="输出完整 job 响应。")
@friendly_errors
def job_continue(job_id: str, until: str, run_to_end: bool, as_json: bool) -> None:
    if until and run_to_end:
        raise click.ClickException("--until and --end are mutually exclusive")
    action = "end" if run_to_end else "continue"
    result = client_from_config().continue_job(job_id, action=action, until=until)
    if as_json:
        click.echo(_json(result))
        return
    click.echo(
        f"job_id={result.get('job_id') or job_id} "
        f"status={result.get('status') or '-'} action={action}"
        + (f" until={until}" if until else "")
    )


@job.command("artifact")
@click.argument("job_id")
@click.argument("name")
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="写入本地文件；不会把二进制内容打印进 Agent 上下文。",
)
@friendly_errors
def job_artifact(job_id: str, name: str, output: Path) -> None:
    response = client_from_config().job_artifact(job_id, name)
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(f".{output.name}.part")
    staging.write_bytes(response.content)
    staging.replace(output)
    click.echo(_json({
        "job_id": job_id,
        "name": name,
        "path": str(output),
        "content_type": response.content_type,
        "content_hash": hashlib.sha256(response.content).hexdigest(),
        "size_bytes": len(response.content),
    }))


@job.command("download-all")
@click.argument("job_id")
@click.option(
    "--output",
    required=False,
    type=click.Path(file_okay=False, path_type=Path),
    help="写入本地目录；省略时使用当前 workspace 的专用 Job 目录。",
)
@friendly_errors
def job_download_all(job_id: str, output: Path | None) -> None:
    client = client_from_config()
    detail = client.get_job(job_id)
    if output is None:
        workspace_id = str(detail.get("workspace_id") or load_state().workspace_id or "unknown")
        output = Path.home() / ".factortester" / "workspaces" / workspace_id / "jobs" / job_id
    response = client.job_artifact_archive(job_id)
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"job-{job_id}-artifacts.zip"
    staging = target.with_name(f".{target.name}.part")
    staging.write_bytes(response.content)
    staging.replace(target)
    click.echo(_json({
        "job_id": job_id,
        "path": str(target),
        "content_type": response.content_type,
        "content_hash": hashlib.sha256(response.content).hexdigest(),
        "size_bytes": len(response.content),
    }))


@job.command("output-capabilities")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读能力声明。")
@friendly_errors
def job_output_capabilities(as_json: bool) -> None:
    capabilities = client_from_config().job_artifact_capabilities()
    if as_json:
        click.echo(_json({"outputs": capabilities}))
        return
    for item in capabilities:
        requires = ",".join(item.get("requires") or ()) or "无"
        modes = ",".join(mode for mode in ("before_run", "after_run") if item.get(mode))
        click.echo(f"{item.get('name')}\t{item.get('label')}\t{modes}\t依赖: {requires}")


@job.command("artifacts")
@click.argument("job_id")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 artifact 元数据。")
@friendly_errors
def job_artifacts(job_id: str, as_json: bool) -> None:
    artifacts = client_from_config().list_job_artifacts(job_id)
    if as_json:
        click.echo(_json({"job_id": job_id, "artifacts": artifacts}))
        return
    for item in artifacts:
        click.echo(f"{item.get('name')}\t{item.get('state')}\t{item.get('size_bytes')} bytes")


@job.command("generate")
@click.argument("job_id")
@click.option("--output", "output_requests", multiple=True, required=True, help="事后生成的输出名，可重复。")
@friendly_errors
def job_generate(job_id: str, output_requests: tuple[str, ...]) -> None:
    click.echo(_json(client_from_config().generate_job_artifacts(
        job_id, output_requests=list(output_requests),
    )))


@job.command("clear-results")
@click.argument("job_id", required=False)
@click.option("--workspace", "current_workspace", is_flag=True, help="清除当前工作区的完整结果。")
@click.option("--all", "all_results", is_flag=True, help="清除当前用户的全部完整结果。")
@friendly_errors
def job_clear_results(job_id: str | None, current_workspace: bool, all_results: bool) -> None:
    selected = int(bool(job_id)) + int(current_workspace) + int(all_results)
    if selected != 1:
        raise click.ClickException("请指定 JOB_ID、--workspace 或 --all 三者之一")
    client = client_from_config()
    if job_id:
        result = client.delete_job_artifacts(job_id)
    else:
        workspace_id = _require_workspace().workspace_id if current_workspace else ""
        result = client.delete_user_artifacts(workspace_id=workspace_id)
    click.echo(_json(result))


@job.command("clear-history")
@click.option(
    "--workspace",
    "current_workspace",
    is_flag=True,
    required=True,
    help="删除当前工作区已成功、失败或取消的任务记录；活动任务不受影响。",
)
@friendly_errors
def job_clear_history(current_workspace: bool) -> None:
    state = _require_workspace()
    result = client_from_config().delete_terminal_job_history(
        workspace_id=state.workspace_id,
    )
    click.echo(_json(result))


@job.command("storage")
@friendly_errors
def job_storage() -> None:
    click.echo(_json(client_from_config().job_storage()))
