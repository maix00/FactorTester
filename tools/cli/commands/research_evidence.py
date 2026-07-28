"""CLI surface for persistent reusable research Evidence."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.core.context import client_from_config


@click.group("research-evidence")
def research_evidence() -> None:
    """Store and qualify reusable Evidence without copying it into Graph."""


@research_evidence.command("put")
@click.option("--envelope-file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--applicability-file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def put(envelope_file: Path, applicability_file: Path, as_json: bool) -> None:
    result = client_from_config().put_research_evidence(
        _read_object(envelope_file), _read_object(applicability_file),
    )
    _emit(result, as_json)


@research_evidence.command("get")
@click.argument("evidence_ref")
@click.option("--json", "as_json", is_flag=True)
def get(evidence_ref: str, as_json: bool) -> None:
    _emit(client_from_config().get_research_evidence(evidence_ref), as_json)


@research_evidence.command("admit")
@click.argument("evidence_ref")
@click.option("--environment-ref", required=True)
@click.option("--subject-ref", required=True)
@click.option("--qualification", type=click.Choice(["unreviewed", "eligible", "limited", "rejected"]), required=True)
@click.option("--note", default="")
@click.option("--json", "as_json", is_flag=True)
def admit(evidence_ref: str, environment_ref: str, subject_ref: str, qualification: str, note: str, as_json: bool) -> None:
    _emit(client_from_config().admit_research_evidence(
        evidence_ref, environment_ref=environment_ref,
        subject_ref=subject_ref, qualification=qualification, note=note,
    ), as_json)


@research_evidence.command("admit-graph")
@click.argument("evidence_ref")
@click.option("--instance-id", required=True)
@click.option("--branch-id", required=True)
@click.option("--qualification", type=click.Choice(["unreviewed", "eligible", "limited", "rejected"]), required=True)
@click.option("--note", default="")
@click.option("--json", "as_json", is_flag=True)
def admit_graph(
    evidence_ref: str, instance_id: str, branch_id: str,
    qualification: str, note: str, as_json: bool,
) -> None:
    """Admit Evidence for one Graph branch using server-derived scope."""
    _emit(client_from_config().admit_research_evidence_for_graph(
        evidence_ref, instance_id=instance_id, branch_id=branch_id,
        qualification=qualification, note=note,
    ), as_json)


def _read_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"invalid JSON file: {path}") from exc
    if not isinstance(value, dict):
        raise click.ClickException(f"JSON file must contain an object: {path}")
    return value


def _emit(value: object, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
