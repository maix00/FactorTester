"""High-level, read-only Research Step batch-1 commands."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.protocols.research_step import validate_prepare_contract


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"invalid JSON file: {path}") from exc
    if not isinstance(value, dict):
        raise click.ClickException("JSON document must be an object")
    return value


def _write(path: Path | None, value: dict[str, Any]) -> None:
    if path is None:
        click.echo(_json(value))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_json(value) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    click.echo(_json({"output": str(path), "output_bytes": path.stat().st_size}))


@click.group("research")
def research() -> None:
    """Run the high-level factor-research workflow."""


@research.group("step")
def research_step() -> None:
    """Inspect and prepare one bounded current Evidence Action."""


@research_step.command("inspect")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path))
@friendly_errors
def inspect_step(instance_id: str, branch_id: str, output: Path | None) -> None:
    """Read the compact authoritative Profile/workspace/action contract."""
    value = client_from_config().inspect_research_step(instance_id, branch_id)
    _write(output, value)


@research_step.command("prepare")
@click.option(
    "--inspect-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--request-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
@friendly_errors
def prepare_step(
    inspect_file: Path,
    request_file: Path,
    output: Path,
) -> None:
    """Validate N configuration identities and write an ephemeral contract."""
    inspect = _read(inspect_file)
    value = client_from_config().prepare_research_step(
        instance_id=str(inspect["binding"]["instance_id"]),
        branch_id=str(inspect["binding"]["branch_id"]),
        request=_read(request_file),
    )
    _write(output, value)


@research_step.command("validate")
@click.option(
    "--contract-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def validate_step(contract_file: Path) -> None:
    """Validate structure offline; execute must refresh server authority."""
    try:
        value = validate_prepare_contract(_read(contract_file))
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(_json(value))
