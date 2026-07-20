"""Thin CLI-Anything adapter for the server-owned Research Cycle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from ..core.cycle import (
    validate_next_packet,
    validate_transition_evidence,
)
from ..core.evidence import persist_command_evidence
from ..core.session import load_session, record_event, save_session
from ..utils.factortester_backend import run_factortester
from .common import echo_json


@click.group("cycle")
def cycle() -> None:
    """Read, validate, and advance one bounded Research Cycle."""


@cycle.command("next")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def cycle_next(
    instance_id: str,
    branch_id: str,
    as_json: bool,
) -> None:
    """Read the server's compact current-node packet without local writes."""
    result = run_factortester([
        "research-graph",
        "next",
        instance_id,
        branch_id,
    ], timeout=60)
    try:
        packet = validate_next_packet(
            _backend_json(result.returncode, result.stdout, result.stderr)
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        echo_json(packet)
        return
    click.echo(
        f"node: {(packet.get('node') or {}).get('node_id', '')}"
    )
    click.echo(f"next_bytes: {packet.get('next_bytes', 0)}")


@cycle.command("inspect")
@click.argument("instance_id")
@click.argument("branch_id")
@click.argument("object_type", type=click.Choice(["claim", "obligation"]))
@click.argument("object_id")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def cycle_inspect(
    instance_id: str,
    branch_id: str,
    object_type: str,
    object_id: str,
    as_json: bool,
) -> None:
    """Only load one Claim or obligation body after a packet references it."""
    result = run_factortester([
        "research-graph",
        "cycle-object",
        instance_id,
        branch_id,
        object_type,
        object_id,
    ], timeout=60)
    value = _backend_json(
        result.returncode,
        result.stdout,
        result.stderr,
    )
    if as_json:
        echo_json(value)
        return
    click.echo(f"{object_type}: {object_id}")


@cycle.command("continuation-preview")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--target-version", required=True, type=click.IntRange(min=1))
@click.option("--job-id", required=True)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def cycle_continuation_preview(
    instance_id: str,
    branch_id: str,
    target_version: int,
    job_id: str,
    as_json: bool,
) -> None:
    """Read the exact continuation hash without changing any state."""
    result = run_factortester([
        "research-graph",
        "continuation-preview",
        instance_id,
        branch_id,
        "--target-version",
        str(target_version),
        "--job-id",
        job_id,
    ], timeout=60)
    payload = _backend_json(
        result.returncode,
        result.stdout,
        result.stderr,
    )
    if as_json:
        echo_json(payload)
        return
    click.echo(f"target_hash: {payload.get('target_hash', '')}")


@cycle.command("continue")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--target-version", required=True, type=click.IntRange(min=1))
@click.option("--job-id", required=True)
@click.option("--expected-target-hash", required=True)
@click.option("--human-authorization-id", required=True)
@click.option("--timeout", default=120, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def cycle_continue(
    ctx: click.Context,
    instance_id: str,
    branch_id: str,
    target_version: int,
    job_id: str,
    expected_target_hash: str,
    human_authorization_id: str,
    timeout: int,
    as_json: bool,
) -> None:
    """Consume one exact Gate and retain a bounded local command receipt."""
    result = run_factortester([
        "research-graph",
        "continue",
        instance_id,
        branch_id,
        "--target-version",
        str(target_version),
        "--job-id",
        job_id,
        "--expected-target-hash",
        expected_target_hash,
        "--human-authorization-id",
        human_authorization_id,
    ], timeout=timeout)
    backend = _backend_json(
        result.returncode,
        result.stdout,
        result.stderr,
    )
    session_path = str(ctx.obj["session_path"])
    session = load_session(session_path)
    envelope = persist_command_evidence(
        session_path=session_path,
        envelope_id=(
            f"continuation-{len(session.evidence_envelopes) + 1}"
        ),
        argv=result.argv,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        hypotheses_tested=session.hypotheses_tested,
        stop_condition=None,
    )
    session.evidence_envelopes.append(envelope)
    record_event(
        session,
        "graph_continuation_created",
        source_instance_id=instance_id,
        source_branch_id=branch_id,
        target_graph_version=target_version,
        target_hash=expected_target_hash,
        evidence_envelope_hash=envelope["envelope_hash"],
    )
    save_session(session, session_path)
    payload = {
        "backend": backend,
        "evidence_envelope_hash": envelope["envelope_hash"],
    }
    if as_json:
        echo_json(payload)
        return
    click.echo(f"graph_version: {target_version}")
    click.echo(f"evidence: {envelope['envelope_hash']}")


@cycle.command("validate")
@click.option(
    "--evidence-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def cycle_validate(evidence_file: Path, as_json: bool) -> None:
    """Validate local proposals without contacting the server."""
    evidence = _load_evidence(evidence_file)
    try:
        validation = validate_transition_evidence(evidence)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {"valid": True, **validation}
    if as_json:
        echo_json(payload)
        return
    click.echo(
        f"valid: proposals={validation['proposal_count']}"
    )


@cycle.command("advance")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--edge-id", required=True)
@click.option(
    "--evidence-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--target-capability-resolution-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--timeout", default=120, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def cycle_advance(
    ctx: click.Context,
    instance_id: str,
    branch_id: str,
    edge_id: str,
    evidence_file: Path,
    target_capability_resolution_file: Path | None,
    timeout: int,
    as_json: bool,
) -> None:
    """Validate locally, then submit through the real FactorTester client."""
    evidence = _load_evidence(evidence_file)
    try:
        validation = validate_transition_evidence(evidence)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    args = [
        "research-graph",
        "advance",
        instance_id,
        branch_id,
        "--edge-id",
        edge_id,
        "--evidence-file",
        str(evidence_file),
    ]
    if target_capability_resolution_file is not None:
        args.extend([
            "--target-capability-resolution-file",
            str(target_capability_resolution_file),
        ])
    result = run_factortester(args, timeout=timeout)
    backend = _backend_json(
        result.returncode,
        result.stdout,
        result.stderr,
    )
    session_path = str(ctx.obj["session_path"])
    session = load_session(session_path)
    envelope = persist_command_evidence(
        session_path=session_path,
        envelope_id=f"cycle-{len(session.evidence_envelopes) + 1}",
        argv=result.argv,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        hypotheses_tested=session.hypotheses_tested,
        stop_condition=None,
    )
    session.evidence_envelopes.append(envelope)
    record_event(
        session,
        "research_cycle_advanced",
        instance_id=instance_id,
        branch_id=branch_id,
        edge_id=edge_id,
        proposal_count=validation["proposal_count"],
        evidence_envelope_hash=envelope["envelope_hash"],
    )
    save_session(session, session_path)
    payload = {
        "backend": backend,
        "local_validation": validation,
        "evidence_envelope_hash": envelope["envelope_hash"],
    }
    if as_json:
        echo_json(payload)
        return
    click.echo(f"edge: {edge_id}")
    click.echo(f"evidence: {envelope['envelope_hash']}")


def _load_evidence(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise click.ClickException("transition evidence must be an object")
    return value


def _backend_json(
    returncode: int,
    stdout: str,
    stderr: str,
) -> dict[str, Any]:
    if returncode != 0:
        raise click.ClickException(
            (stderr or stdout or "FactorTester command failed")[:1000]
        )
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise click.ClickException(
            "FactorTester returned invalid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise click.ClickException("FactorTester JSON must be an object")
    return value
