"""Research workspace, configuration, template, run, and job commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.state import load_state, save_state


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


@click.group("run")
def run() -> None:
    """Submit and inspect immutable research runs."""


@run.command("preview")
@click.option("--analysis", "analyses", multiple=True, type=click.Choice([
    "backtest", "ic", "factor_evaluation", "factor_type_analysis",
]), required=True)
@click.option("--retain-full", is_flag=True, help="预览完整结果保留模式。")
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
    step_mode: bool,
) -> None:
    """Preview the exact frozen RunSpec identity without creating state."""
    state = _require_workspace()
    result = client_from_config().preview_run(
        state.workspace_id,
        state.configuration_revision,
        analyses=list(analyses),
        retention_mode="full" if retain_full else "summary",
        step_mode=step_mode,
    )
    click.echo(_json(result))


@run.command("submit")
@click.option("--analysis", "analyses", multiple=True, type=click.Choice([
    "backtest", "ic", "factor_evaluation", "factor_type_analysis",
]), required=True)
@click.option("--retain-full", is_flag=True, help="在服务器配额内保留完整曲线和明细。")
@click.option("--step", "step_mode", is_flag=True, help="逐 flow 暂停，仅支持单个 backtest。")
@click.option(
    "--trial-binding-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="绑定当前 Hypothesis Branch 已冻结 TrialPlan 的 JSON 文件。",
)
@friendly_errors
def run_submit(
    analyses: tuple[str, ...],
    retain_full: bool,
    step_mode: bool,
    trial_binding_file: Path | None,
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
    result = client_from_config().submit_run(
        state.workspace_id,
        state.configuration_revision,
        analyses=list(analyses),
        retention_mode="full" if retain_full else "summary",
        step_mode=step_mode,
        trial_binding=trial_binding,
    )
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
def job() -> None:
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
    rows = client_from_config().list_jobs(
        workspace_id=workspace_id,
        status=",".join(statuses),
        kind=kind or "",
        limit=limit,
    )
    if as_json:
        click.echo(_json({"jobs": rows, "count": len(rows)}))
        return
    for item in rows:
        click.echo(
            f"{item.get('job_id')} run={item.get('run_id')} kind={item.get('kind')} "
            f"status={item.get('status')} attempt={item.get('attempt')}"
        )


@job.command("status")
@click.argument("job_id")
@friendly_errors
def job_status(job_id: str) -> None:
    click.echo(_json(client_from_config().get_job(job_id)))


@job.command("result")
@click.argument("job_id")
@friendly_errors
def job_result(job_id: str) -> None:
    """Read the retained result, cancellation detail, or failure traceback."""
    click.echo(_json(client_from_config().job_result(job_id)))


@job.command("watch")
@click.argument("job_id")
@click.option("--after", default=0, type=int)
@friendly_errors
def job_watch(job_id: str, after: int) -> None:
    for event in client_from_config().stream_job_id(job_id, after=after):
        click.echo(_json(event))


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
@friendly_errors
def job_continue(job_id: str, until: str, run_to_end: bool) -> None:
    if until and run_to_end:
        raise click.ClickException("--until and --end are mutually exclusive")
    action = "end" if run_to_end else "until" if until else "continue"
    click.echo(_json(client_from_config().continue_job(job_id, action=action, until=until)))


@job.command("artifact")
@click.argument("job_id")
@click.argument("name")
@friendly_errors
def job_artifact(job_id: str, name: str) -> None:
    click.echo(_json(client_from_config().job_artifact(job_id, name)))


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
