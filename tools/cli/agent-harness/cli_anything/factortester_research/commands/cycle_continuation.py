"""Continuation reads and mutation for one Research Cycle branch."""

from __future__ import annotations

import json

import click

from ..core.evidence import persist_command_evidence
from ..core.session import load_session, record_event, save_session
from ..utils.factortester_backend import run_factortester
from .common import echo_json


@click.command("continuation-preview")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--target-version", required=True, type=click.IntRange(min=1))
@click.option("--job-id", default="", help="Bound Job；omit only for a paused pre-TrialPlan branch.")
@click.option("--mode", "execution_mode", type=click.Choice(["live", "shadow"]), default="live", show_default=True)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def cycle_continuation_preview(instance_id: str, branch_id: str, target_version: int, job_id: str, execution_mode: str, as_json: bool) -> None:
    """Read the exact continuation hash without changing any state."""
    arguments = [
        "research-graph", "continuation-preview", instance_id, branch_id,
        "--target-version", str(target_version), "--mode", execution_mode,
    ]
    if job_id:
        arguments.extend(["--job-id", job_id])
    payload = _backend_json(run_factortester(arguments, timeout=60))
    if as_json:
        echo_json(payload)
        return
    click.echo(f"target_hash: {payload.get('target_hash', '')}")


@click.command("continue")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--target-version", required=True, type=click.IntRange(min=1))
@click.option("--job-id", default="", help="Bound Job；omit only for a paused pre-TrialPlan branch.")
@click.option("--mode", "execution_mode", type=click.Choice(["live", "shadow"]), default="live", show_default=True)
@click.option("--expected-target-hash", required=True)
@click.option("--timeout", default=120, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def cycle_continue(ctx: click.Context, instance_id: str, branch_id: str, target_version: int, job_id: str, execution_mode: str, expected_target_hash: str, timeout: int, as_json: bool) -> None:
    """Consume one exact Gate and retain a bounded local command receipt."""
    arguments = [
        "research-graph", "continue", instance_id, branch_id,
        "--target-version", str(target_version),
        "--expected-target-hash", expected_target_hash,
        "--mode", execution_mode,
    ]
    if job_id:
        arguments.extend(["--job-id", job_id])
    result = run_factortester(arguments, timeout=timeout)
    backend = _backend_json(result)
    session_path = str(ctx.obj["session_path"])
    session = load_session(session_path)
    envelope = persist_command_evidence(
        session_path=session_path,
        envelope_id=f"continuation-{len(session.evidence_envelopes) + 1}",
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
    payload = {"backend": backend, "evidence_envelope_hash": envelope["envelope_hash"]}
    if as_json:
        echo_json(payload)
        return
    click.echo(f"graph_version: {target_version}")
    click.echo(f"evidence: {envelope['envelope_hash']}")


def _backend_json(result) -> dict:
    if result.returncode != 0:
        raise click.ClickException(
            (result.stderr or result.stdout or "FactorTester command failed")[:1000]
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise click.ClickException("FactorTester returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise click.ClickException("FactorTester JSON must be an object")
    return value
