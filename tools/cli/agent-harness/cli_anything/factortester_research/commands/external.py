"""External factor planning and artifact-contract validation."""

from __future__ import annotations

import shlex

import click

from ..core.external_factor import (
    validate_dataset_manifest,
    validate_factor_manifest,
    validate_handoff_manifest,
    vibe_pipeline_plan,
)
from ..core.session import load_session, record_event, save_session
from .common import echo_json

@click.group("external-factor")
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
        echo_json({"steps": payload})
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
        echo_json({"valid": True, "artifacts": results})
        return
    for item in results:
        click.echo(f"OK {item['kind']}: {item['path']}")
