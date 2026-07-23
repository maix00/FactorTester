"""Local authoring commands for current-node Entry Requirements."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

import click

from ..core.cycle import validate_next_packet
from ..core.entry_preparation import (
    build_entry_assessment_skeleton,
    compact_factor_facts,
    validate_entry_assessment_document,
)
from ..utils.factortester_backend import run_factortester
from .common import echo_json


@click.command("entry-prepare")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--factor-family", required=True)
@click.option(
    "--requirement-id",
    "requirement_ids",
    multiple=True,
    required=True,
    help="只读取并准备这一项当前节点要求；可重复。",
)
@click.option(
    "--factor-source",
    type=click.Choice(["auto", "custom", "public"]),
    default="auto",
    show_default=True,
)
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def entry_prepare(
    instance_id: str,
    branch_id: str,
    factor_family: str,
    requirement_ids: tuple[str, ...],
    factor_source: str,
    output: Path,
    as_json: bool,
) -> None:
    """Prepare an editable, selected-requirement assessment document."""
    try:
        packet = validate_next_packet(_call_json([
            "research-graph", "next", instance_id, branch_id,
        ]))
        details = {
            requirement_id: _call_json([
                "research-graph", "requirement-detail",
                instance_id, branch_id, requirement_id,
            ])
            for requirement_id in dict.fromkeys(requirement_ids)
        }
        describe = _call_json([
            "custom_factors", "describe", factor_family,
            "--source", factor_source, "--debug-graph", "--json",
        ])
        document = build_entry_assessment_skeleton(
            next_packet=packet,
            requirement_details=details,
            factor_facts=compact_factor_facts(
                describe,
                factor_ref=factor_family,
            ),
            selected_requirement_ids=list(requirement_ids),
        )
        _atomic_json(output, document)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        echo_json({
            "output": str(output),
            "output_bytes": output.stat().st_size,
            "context": document["context"],
            "selected_requirement_ids": document[
                "selected_requirement_ids"
            ],
            "expression_ref": document["factor_facts"]["expression_ref"],
        })
        return
    click.echo(f"entry assessment draft: {output}")
    click.echo(f"requirements: {len(document['assessments'])}")


@click.command("entry-validate")
@click.option(
    "--document-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="可选：写出紧凑 assessment/report projection。",
)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def entry_validate(
    document_file: Path,
    output: Path | None,
    as_json: bool,
) -> None:
    """Validate an edited draft and derive hashes before backend mutation."""
    try:
        document = json.loads(document_file.read_text(encoding="utf-8"))
        projection = validate_entry_assessment_document(document)
        if output is not None:
            _atomic_json(output, projection)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        if output is None:
            echo_json(projection)
        else:
            echo_json({
                "valid": True,
                "output": str(output),
                "output_bytes": output.stat().st_size,
                "requirement_count": len(
                    projection["entry_requirement_assessments"]
                ),
                "report_fragment_hash": projection[
                    "report_submission"
                ]["fragment_hash"],
            })
        return
    click.echo("entry assessment: valid")
    click.echo(
        f"requirements: {len(projection['entry_requirement_assessments'])}"
    )
    if output is not None:
        click.echo(f"projection: {output}")


def _call_json(args: list[str]) -> dict[str, Any]:
    result = run_factortester(args, timeout=60)
    if result.returncode != 0:
        raise ValueError(
            (result.stderr or result.stdout or "FactorTester command failed")[
                :1000
            ]
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("FactorTester returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("FactorTester JSON must be an object")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    """Publish one local file atomically without a database or platform lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
