"""Durable research workspace, run, and job commands."""

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
    """Manage durable research workspaces."""


@workspace.command("create")
@click.option("--factor-family", required=True)
@click.option("--title", default="Single factor research", show_default=True)
@friendly_errors
def workspace_create(factor_family: str, title: str) -> None:
    value = client_from_config().create_workspace(
        factor_family_alias=factor_family,
        title=title,
    )
    state = load_state()
    state.workspace_id = str(value["workspace_id"])
    state.workspace_revision = int(value["revision"])
    state.factor_family = factor_family
    save_state(state)
    click.echo(f"workspace_id={state.workspace_id} revision={state.workspace_revision}")


@workspace.command("list")
@friendly_errors
def workspace_list() -> None:
    for item in client_from_config().list_workspaces():
        click.echo(
            f"{item.get('workspace_id')} revision={item.get('revision')} "
            f"factor={item.get('factor_family_alias') or '-'} title={item.get('title') or '-'}"
        )


@workspace.command("use")
@click.argument("workspace_id")
@friendly_errors
def workspace_use(workspace_id: str) -> None:
    value = client_from_config().get_workspace(workspace_id)
    state = load_state()
    state.workspace_id = workspace_id
    state.workspace_revision = int(value["revision"])
    state.factor_family = str(value.get("factor_family_alias") or "")
    save_state(state)
    click.echo(f"workspace_id={workspace_id} revision={state.workspace_revision}")


@workspace.command("show")
@friendly_errors
def workspace_show() -> None:
    state = _require_workspace()
    click.echo(_json(client_from_config().get_workspace(state.workspace_id)))


@workspace.command("update")
@click.option("--draft-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@friendly_errors
def workspace_update(draft_file: Path) -> None:
    state = _require_workspace()
    draft = json.loads(draft_file.read_text(encoding="utf-8"))
    if not isinstance(draft, dict):
        raise click.ClickException("draft JSON must be an object")
    value = client_from_config().update_workspace(
        state.workspace_id,
        expected_revision=state.workspace_revision,
        draft=draft,
    )
    state.workspace_revision = int(value["revision"])
    save_state(state)
    click.echo(f"workspace_id={state.workspace_id} revision={state.workspace_revision}")


@click.group("run")
def run() -> None:
    """Submit and inspect immutable research runs."""


@run.command("submit")
@click.option("--analysis", "analyses", multiple=True, type=click.Choice([
    "backtest", "ic", "factor_evaluation", "factor_type_analysis",
]), required=True)
@click.option("--lifecycle", type=click.Choice(["durable", "observer_bound", "pause_on_detach"]), default="durable")
@friendly_errors
def run_submit(analyses: tuple[str, ...], lifecycle: str) -> None:
    state = _require_workspace()
    result = client_from_config().submit_run(
        state.workspace_id,
        state.workspace_revision,
        analyses=list(analyses),
        lifecycle_policy=lifecycle,
    )
    click.echo(f"run_id={result.get('run_id')}")
    for item in result.get("jobs") or []:
        click.echo(f"job_id={item.get('job_id')} kind={item.get('kind')} status={item.get('status')}")


@run.command("show")
@click.argument("run_id")
@friendly_errors
def run_show(run_id: str) -> None:
    click.echo(_json(client_from_config().get_run(run_id)))


@click.group("job")
def job() -> None:
    """Observe and control durable job attempts."""


@job.command("list")
@click.option("--all-workspaces", is_flag=True)
@click.option("--status", default="")
@friendly_errors
def job_list(all_workspaces: bool, status: str) -> None:
    state = load_state()
    workspace_id = "" if all_workspaces else state.workspace_id
    for item in client_from_config().list_jobs(workspace_id=workspace_id, status=status):
        click.echo(
            f"{item.get('job_id')} run={item.get('run_id')} kind={item.get('kind')} "
            f"status={item.get('status')} attempt={item.get('attempt')}"
        )


@job.command("status")
@click.argument("job_id")
@friendly_errors
def job_status(job_id: str) -> None:
    click.echo(_json(client_from_config().get_job(job_id)))


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


@job.command("continue")
@click.argument("job_id")
@friendly_errors
def job_continue(job_id: str) -> None:
    click.echo(_json(client_from_config().continue_job(job_id)))


@job.command("artifact")
@click.argument("job_id")
@click.argument("name")
@friendly_errors
def job_artifact(job_id: str, name: str) -> None:
    click.echo(_json(client_from_config().job_artifact(job_id, name)))
