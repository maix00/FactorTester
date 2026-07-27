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
from ..core.submission_contract import (
    build_cycle_submission_contract,
    validate_against_cycle_submission_contract,
    validate_contract_for_current_packet,
)
from ..utils.factortester_backend import run_factortester
from tools.cli.release.research_reporting.document import (
    bindings_path_for,
    document_manifest,
    load_bindings,
    load_document,
)
from tools.cli.release.research_reporting.graph_adapter import (
    enrich_graph_packet,
    validate_report_tasks,
)
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
        packet = enrich_graph_packet(validate_next_packet(
            _backend_json(result.returncode, result.stdout, result.stderr)
        ))
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


@cycle.command("requirement")
@click.argument("instance_id")
@click.argument("branch_id")
@click.argument("requirement_id")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def cycle_requirement(
    instance_id: str,
    branch_id: str,
    requirement_id: str,
    as_json: bool,
) -> None:
    """Lazy-load one requirement only after ``cycle next`` references it."""
    result = run_factortester([
        "research-graph",
        "requirement-detail",
        instance_id,
        branch_id,
        requirement_id,
    ], timeout=60)
    value = _backend_json(
        result.returncode,
        result.stdout,
        result.stderr,
    )
    if as_json:
        echo_json(value)
        return
    requirement = value.get("requirement") or {}
    click.echo(
        f"requirement: {requirement.get('requirement_id', requirement_id)}"
    )


@cycle.command("continuation-preview")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--target-version", required=True, type=click.IntRange(min=1))
@click.option(
    "--job-id",
    default="",
    help="Bound Job; omit only for a paused pre-TrialPlan branch.",
)
@click.option(
    "--mode",
    "execution_mode",
    type=click.Choice(["live", "shadow"]),
    default="live",
    show_default=True,
)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def cycle_continuation_preview(
    instance_id: str,
    branch_id: str,
    target_version: int,
    job_id: str,
    execution_mode: str,
    as_json: bool,
) -> None:
    """Read the exact continuation hash without changing any state."""
    arguments = [
        "research-graph",
        "continuation-preview",
        instance_id,
        branch_id,
        "--target-version",
        str(target_version),
        "--mode",
        execution_mode,
    ]
    if job_id:
        arguments.extend(["--job-id", job_id])
    result = run_factortester(arguments, timeout=60)
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
@click.option(
    "--job-id",
    default="",
    help="Bound Job; omit only for a paused pre-TrialPlan branch.",
)
@click.option(
    "--mode",
    "execution_mode",
    type=click.Choice(["live", "shadow"]),
    default="live",
    show_default=True,
)
@click.option("--expected-target-hash", required=True)
@click.option("--timeout", default=120, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def cycle_continue(
    ctx: click.Context,
    instance_id: str,
    branch_id: str,
    target_version: int,
    job_id: str,
    execution_mode: str,
    expected_target_hash: str,
    timeout: int,
    as_json: bool,
) -> None:
    """Consume one exact Gate and retain a bounded local command receipt."""
    arguments = [
        "research-graph",
        "continue",
        instance_id,
        branch_id,
        "--target-version",
        str(target_version),
        "--expected-target-hash",
        expected_target_hash,
        "--mode",
        execution_mode,
    ]
    if job_id:
        arguments.extend(["--job-id", job_id])
    result = run_factortester(arguments, timeout=timeout)
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
@click.option(
    "--contract-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="可选：同时按 cycle prepare 生成的当前步骤合同校验。",
)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def cycle_validate(
    evidence_file: Path,
    contract_file: Path | None,
    as_json: bool,
) -> None:
    """Validate local proposals without contacting the server."""
    evidence = _load_evidence(evidence_file)
    try:
        validation = validate_transition_evidence(evidence)
        if contract_file is not None:
            contract = _load_evidence(contract_file)
            validation.update(
                validate_against_cycle_submission_contract(
                    evidence, contract,
                )
            )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {"valid": True, **validation}
    if as_json:
        echo_json(payload)
        return
    click.echo(
        f"valid: proposals={validation['proposal_count']}"
    )


@cycle.command("prepare")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--edge-id", required=True)
@click.option(
    "--evidence-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="可选：从已有提案推导 reviewer task_ref 等动态要求。",
)
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
def cycle_prepare(
    instance_id: str,
    branch_id: str,
    edge_id: str,
    evidence_file: Path | None,
    output: Path,
    as_json: bool,
) -> None:
    """Generate the exact local wire contract for one current candidate edge."""
    try:
        packet = enrich_graph_packet(validate_next_packet(_backend_json_result([
            "research-graph", "next", instance_id, branch_id,
        ])))
        evidence = (
            _load_evidence(evidence_file)
            if evidence_file is not None else None
        )
        contract = build_cycle_submission_contract(
            packet, edge_id=edge_id, evidence=evidence,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                contract, ensure_ascii=False, indent=2, sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {
        "output": str(output),
        "output_bytes": output.stat().st_size,
        "edge_id": edge_id,
        "from_node": contract["transition"]["from_node"],
        "to_node": contract["transition"]["to_node"],
        "reusable_obligation_count": len(
            contract["reusable_refs"]["obligations"]
        ),
        "required_reviewer_task_refs": (
            contract.get("derived_requirements") or {}
        ).get("required_reviewer_task_refs", []),
        "required_report_tasks": [
            item["task_ref"]
            for item in (packet.get("report_packet") or {}).get("required_tasks") or []
        ],
    }
    if as_json:
        echo_json(payload)
        return
    click.echo(f"cycle submission contract: {output}")
    click.echo(f"edge: {edge_id}")


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
    "--contract-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help=(
        "推荐：提交前按 cycle prepare 的当前步骤合同校验并确认未过期；"
        "省略时保留旧版仅本地/服务器校验路径。"
    ),
)
@click.option(
    "--target-capability-resolution-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--acting-profile-ref", default="")
@click.option(
    "--report-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help=(
        "可选：提交前校验通用报告文档；仅生成本地 manifest，"
        "不会把正文写入 Active Graph"
    ),
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
    contract_file: Path | None,
    target_capability_resolution_file: Path | None,
    acting_profile_ref: str,
    report_file: Path | None,
    timeout: int,
    as_json: bool,
) -> None:
    """Validate locally, then submit through the real FactorTester client."""
    evidence = _load_evidence(evidence_file)
    try:
        validation = validate_transition_evidence(evidence)
        if contract_file is not None:
            contract = _load_evidence(contract_file)
            contract_edge = str(
                (contract.get("transition") or {}).get("edge_id") or ""
            )
            if contract_edge != edge_id:
                raise ValueError(
                    "submission contract edge_id does not match --edge-id"
                )
            validation.update(
                validate_against_cycle_submission_contract(
                    evidence, contract,
                )
            )
            current_packet = enrich_graph_packet(validate_next_packet(_backend_json_result([
                "research-graph", "next", instance_id, branch_id,
            ])))
            validation.update(validate_contract_for_current_packet(
                contract, current_packet, edge_id=edge_id,
            ))
        if report_file is not None:
            report_document = load_document(report_file)
            bindings_file = bindings_path_for(report_file)
            report_bindings = load_bindings(bindings_file, report_document)
            report_status = validate_report_tasks(
                enrich_graph_packet(validate_next_packet(_backend_json_result([
                    "research-graph", "next", instance_id, branch_id,
                ]))),
                report_bindings,
            )
            if not report_status["valid"]:
                raise ValueError(
                    "report checklist is incomplete: "
                    + ", ".join(report_status["missing"])
                )
            validation["report_checklist"] = report_status
            validation["report_document"] = {
                "mode": "local_manifest_only",
                "submission_note": (
                    "正文不会写入 Active Graph；需要由 report publisher "
                    "或 Profile 本地报告同步链路持久化。"
                ),
                "manifest": document_manifest(report_document),
                "bindings_file": str(bindings_file),
            }
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
    if acting_profile_ref:
        args.extend(["--acting-profile-ref", acting_profile_ref])
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


def _backend_json_result(args: list[str]) -> dict[str, Any]:
    result = run_factortester(args, timeout=60)
    return _backend_json(result.returncode, result.stdout, result.stderr)
