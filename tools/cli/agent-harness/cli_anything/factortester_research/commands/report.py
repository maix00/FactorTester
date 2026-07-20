"""CLI-Anything adapter for deterministic local research reports."""

from __future__ import annotations

import json
from pathlib import Path

import click

from ..core.reporting import render_branch_report
from .common import echo_json


@click.group("report")
def report() -> None:
    """Render bounded local reports without contacting the server."""


@report.command("render")
@click.option(
    "--snapshot-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--workspace-root",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def report_render(
    snapshot_file: Path,
    workspace_root: Path,
    as_json: bool,
) -> None:
    """Render one content-addressed branch snapshot incrementally."""
    try:
        snapshot = json.loads(snapshot_file.read_text())
        result = render_branch_report(
            snapshot,
            workspace_root=workspace_root,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {**result, "path": str(result["path"])}
    if as_json:
        echo_json(payload)
        return
    click.echo(f"report: {payload['path']}")
    click.echo(f"changed: {str(payload['changed']).lower()}")
