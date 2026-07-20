"""Capture bounded evidence projected by the real FactorTester backend."""

from __future__ import annotations

import json

import click

from ..core.backend_evidence import extract_job_attempt
from ..core.session import load_session, record_event, save_session
from ..utils.factortester_backend import run_factortester
from .common import echo_json


@click.group("evidence")
def evidence() -> None:
    """Capture server-owned evidence without reconstructing its identity."""


@evidence.command("capture-job")
@click.argument("job_id")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def capture_job(
    ctx: click.Context,
    job_id: str,
    as_json: bool,
) -> None:
    """Capture one terminal JobAttempt envelope from authenticated status."""
    result = run_factortester(["job", "status", job_id], timeout=60)
    if result.returncode != 0:
        raise click.ClickException(
            (result.stderr or result.stdout or "FactorTester command failed")[
                :1000
            ]
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise click.ClickException(
            "FactorTester returned invalid job JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise click.ClickException("FactorTester job JSON must be an object")
    try:
        envelope, disposition = extract_job_attempt(payload)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    session_path = str(ctx.obj["session_path"])
    session = load_session(session_path)
    reused = any(
        item.get("envelope_hash") == envelope["envelope_hash"]
        for item in session.evidence_envelopes
        if isinstance(item, dict)
    )
    if not reused:
        session.evidence_envelopes.append(envelope)
    record_event(
        session,
        "job_evidence_captured",
        job_id=job_id,
        evidence_envelope_hash=envelope["envelope_hash"],
        assurance_disposition=disposition,
        reused=reused,
    )
    save_session(session, session_path)
    output = {
        "evidence_envelope": envelope,
        "assurance_disposition": disposition,
        "reused": reused,
    }
    if as_json:
        echo_json(output)
        return
    click.echo(
        f"job: {job_id} · assurance={disposition} · reused={reused}"
    )
