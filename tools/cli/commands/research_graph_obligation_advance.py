"""Prepare and receipt one ledger-backed Research Graph advance."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from tools.cli.release.research_obligations import (
    append_event,
    canonicalize_ledger,
    load_ledger,
    ledger_hash,
    obligations as packet_obligations,
    project_requirement_coverage,
    requirement_title_overrides,
    requirement_union,
    requirements as packet_requirements,
    write_ledger,
)
from tools.cli.release.research_obligations.reporting import (
    node_exit_operations,
)
from tools.cli.release.research_obligations.transition_report import (
    target_container_operations,
)
from tools.cli.release.research_reporting.authoring.submission_begin import (
    begin_submission,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    apply_batch,
)
from tools.cli.release.research_reporting.authoring.tree_store import (
    atomic_write,
)
from tools.cli.release.research_reporting.git import commit_work_package
from tools.cli.release.research_reporting.package_layout import (
    safe_package_component,
)

from .research_report_scope import (
    load_current_authoring,
)
from .research_report_scope_identity import BranchReportScope
from .research_report_submission_finalize import finalize_report_command
from .research_graph_report_policy import report_container


_PASSING_COVERAGE = {"satisfied", "limited"}
_WIRE_COVERAGE_FIELDS = (
    "requirement_id", "obligation_refs", "obligation_statuses",
    "node_required", "edge_required", "satisfaction",
)


@dataclass(frozen=True)
class PreparedObligationAdvance:
    attempt_id: str
    evidence: dict[str, Any]
    coverage_submission: dict[str, Any]
    prepared_git_commit: str
    source_report_parent_id: str


def prepare_obligation_advance(
    *,
    package_root: Path,
    branch_id: str,
    node_packet: dict[str, Any],
    edge_packet: dict[str, Any],
    edge_id: str,
    evidence: dict[str, Any],
    source_report_parent_id: str,
) -> PreparedObligationAdvance:
    ledger = load_ledger(package_root, branch_id)
    selected = ledger["current_projection"].get("selected_edge")
    _validate_selection(selected, edge_packet=edge_packet, edge_id=edge_id)
    requirements = requirement_union(node_packet, edge_packet)
    node_requirement_ids = {
        str(item["requirement_id"])
        for item in packet_requirements(node_packet)
    }
    coverage = project_requirement_coverage(
        requirements=requirements,
        obligations=ledger["current_projection"]["obligations"],
        edge_required_ids=set(
            str(item)
            for item in selected.get("required_requirement_ids") or []
        ),
        node_required_ids=node_requirement_ids,
        title_overrides=requirement_title_overrides(ledger),
    )
    wire_coverage = _wire_coverage(coverage)
    submission = _coverage_submission(
        ledger=ledger,
        edge_id=edge_id,
        selected=selected,
        coverage=wire_coverage,
    )
    prepared_evidence = deepcopy(evidence)
    prepared_evidence["entry_requirement_assessments"] = (
        _bind_assessment_coverage(
            prepared_evidence.get("entry_requirement_assessments"),
            wire_coverage,
        )
    )
    cycle = _pending_research_cycle(ledger)
    if cycle is not None:
        supplied = prepared_evidence.get("research_cycle")
        if supplied is not None and supplied != cycle:
            raise ValueError(
                "evidence research_cycle conflicts with the obligation ledger"
            )
        prepared_evidence["research_cycle"] = cycle
    prepared_evidence["obligation_coverage_submission"] = submission
    existing = _unreceipted_prepared(ledger)
    if existing is not None:
        if (
            existing.get("edge_id") != edge_id
            or existing.get("coverage_hash") != submission["coverage_hash"]
            or existing.get("source_report_parent_id")
            != source_report_parent_id
        ):
            raise ValueError(
                "an unreceipted obligation advance already exists"
            )
        prepared_commit = _git_head(package_root)
        prepared_evidence["obligation_coverage_submission"][
            "prepared_git_commit"
        ] = prepared_commit
        return PreparedObligationAdvance(
            attempt_id=str(existing["attempt_id"]),
            evidence=prepared_evidence,
            coverage_submission=prepared_evidence[
                "obligation_coverage_submission"
            ],
            prepared_git_commit=prepared_commit,
            source_report_parent_id=source_report_parent_id,
        )
    attempt_id = _event_id(
        ledger["current_projection"]["projection_hash"],
        {"edge_id": edge_id, "coverage_hash": submission["coverage_hash"]},
    )
    next_ledger = append_event(
        ledger,
        event_type="advance_prepared",
        event_id=attempt_id,
        payload={
            "attempt_id": attempt_id,
            "source_node": ledger["branch"]["current_node"],
            "edge_id": edge_id,
            "target_node": selected["target_node"],
            "context_ref": ledger["branch"]["context_ref"],
            "checkpoint_ref": ledger["branch"]["checkpoint_ref"],
            "coverage_hash": submission["coverage_hash"],
            "coverage_snapshot": coverage,
            "obligations_snapshot": deepcopy(
                ledger["current_projection"]["obligations"]
            ),
            "coverage_submission": submission,
            "source_report_parent_id": source_report_parent_id,
            "base_git_commit": _git_head(package_root),
        },
    )
    write_ledger(package_root, branch_id, next_ledger)
    git = commit_work_package(
        package_root, message="Prepare research Graph advance",
    )
    prepared_commit = str(git["commit"])
    prepared_evidence["obligation_coverage_submission"][
        "prepared_git_commit"
    ] = prepared_commit
    return PreparedObligationAdvance(
        attempt_id=attempt_id,
        evidence=prepared_evidence,
        coverage_submission=prepared_evidence[
            "obligation_coverage_submission"
        ],
        prepared_git_commit=prepared_commit,
        source_report_parent_id=source_report_parent_id,
    )


def record_rejected_advance(
    *,
    package_root: Path,
    branch_id: str,
    prepared: PreparedObligationAdvance,
    status: str,
    error_code: str,
    message: str,
) -> dict[str, Any]:
    if status not in {"local_rejected", "server_rejected"}:
        raise ValueError("rejected advance status is invalid")
    ledger = load_ledger(package_root, branch_id)
    existing = _receipt_for(ledger, prepared.attempt_id)
    if existing is not None:
        return {
            "receipt": existing,
            "git": {
                "committed": False,
                "commit": _git_head(package_root),
            },
        }
    event_id = _event_id(
        prepared.attempt_id,
        {"status": status, "error_code": error_code, "message": message},
    )
    next_ledger = append_event(
        ledger,
        event_type="advance_receipt",
        event_id=event_id,
        payload={
            "attempt_id": prepared.attempt_id,
            "status": status,
            "error_code": error_code,
            "message": message,
            "prepared_git_commit": prepared.prepared_git_commit,
            "trace_ref": "",
            "checkpoint_ref": "",
        },
    )
    write_ledger(package_root, branch_id, next_ledger)
    git = commit_work_package(
        package_root, message="Record rejected research Graph advance",
    )
    return {"receipt": next_ledger["history"][-1], "git": git}


def write_accepted_reconciliation(
    *,
    package_root: Path,
    branch_id: str,
    prepared: PreparedObligationAdvance,
    branch_result: dict[str, Any],
) -> Path:
    path = _reconciliation_path(package_root, branch_id)
    value = {
        "schema_version": 1,
        "attempt_id": prepared.attempt_id,
        "prepared_git_commit": prepared.prepared_git_commit,
        "source_report_parent_id": prepared.source_report_parent_id,
        "branch_result": deepcopy(branch_result),
    }
    atomic_write(path, _canonical_bytes(value) + b"\n")
    return path


def load_accepted_reconciliation(
    package_root: Path,
    branch_id: str,
) -> dict[str, Any] | None:
    path = _reconciliation_path(package_root, branch_id)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("accepted advance reconciliation is invalid") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {
            "schema_version", "attempt_id", "prepared_git_commit",
            "source_report_parent_id", "branch_result",
        }
        or value.get("schema_version") != 1
        or not isinstance(value.get("branch_result"), dict)
    ):
        raise ValueError("accepted advance reconciliation fields are invalid")
    return value


def finalize_accepted_advance(
    *,
    scope: Any,
    next_packet: dict[str, Any],
    reconciliation: dict[str, Any],
    submission_sequence: int | None,
) -> dict[str, Any]:
    ledger = load_ledger(scope.package_root, scope.branch_id)
    attempt_id = str(reconciliation["attempt_id"])
    prepared_event = next((
        item for item in ledger["history"]
        if item.get("event_type") == "advance_prepared"
        and item.get("attempt_id") == attempt_id
    ), None)
    if prepared_event is None:
        raise ValueError("accepted advance has no local prepared event")
    existing = _receipt_for(ledger, attempt_id)
    if existing is not None:
        if existing.get("status") != "accepted":
            raise ValueError(
                "accepted server transition conflicts with a rejected receipt"
            )
        _reconciliation_path(
            scope.package_root, scope.branch_id,
        ).unlink(missing_ok=True)
        return {
            "receipt": existing,
            "git": {
                "committed": False,
                "commit": _git_head(scope.package_root),
            },
        }
    checkpoint_ref = str(next_packet.get("checkpoint_ref") or "")
    branch_result = reconciliation["branch_result"]
    trace_ref = checkpoint_ref or str(
        branch_result.get("latest_trace_ref")
        or (
            f"trace:{branch_result['latest_trace_id']}"
            if branch_result.get("latest_trace_id") else ""
        )
    )
    if not trace_ref:
        raise ValueError("accepted advance response has no trace/checkpoint ref")
    event_id = _event_id(
        attempt_id,
        {
            "status": "accepted",
            "trace_ref": trace_ref,
            "checkpoint_ref": checkpoint_ref or trace_ref,
        },
    )
    next_ledger = append_event(
        ledger,
        event_type="advance_receipt",
        event_id=event_id,
        payload={
            "attempt_id": attempt_id,
            "status": "accepted",
            "error_code": "",
            "message": "",
            "prepared_git_commit": str(
                reconciliation["prepared_git_commit"]
            ),
            "trace_ref": trace_ref,
            "checkpoint_ref": checkpoint_ref or trace_ref,
            "report_components": {},
        },
    )
    receipt = next_ledger["history"][-1]
    exit_event = {
        **prepared_event,
        "receipt": receipt,
    }
    operations, component_ids = node_exit_operations(
        event=exit_event,
        parent_id=str(reconciliation["source_report_parent_id"]),
    )
    target_operations, target_components = target_container_operations(
        package_root=scope.package_root,
        branch_id=scope.branch_id,
        container=report_container(next_packet),
    )
    operations.extend(target_operations)
    receipt["report_components"] = {
        **component_ids,
        "target": target_components,
    }
    next_ledger["branch"] = {
        "branch_ref": ledger["branch"]["branch_ref"],
        "graph_ref": str(next_packet.get("graph") or ""),
        "current_node": str(
            (next_packet.get("node") or {}).get("node_id") or ""
        ),
        "context_ref": str(next_packet.get("context_ref") or ""),
        "checkpoint_ref": checkpoint_ref or trace_ref,
    }
    obligations = packet_obligations(next_packet)
    next_ledger["current_projection"] = {
        "obligations": obligations,
        "requirement_coverage": project_requirement_coverage(
            requirements=packet_requirements(next_packet),
            obligations=obligations,
            title_overrides=requirement_title_overrides(ledger),
        ),
        "selected_edge": None,
        "projection_hash": "",
    }
    next_ledger = canonicalize_ledger(next_ledger)
    sidecar = {
        "path": "obligations.json",
        "base_generation": ledger["generation"],
        "next_generation": next_ledger["generation"],
        "next_hash": ledger_hash(next_ledger),
        "next_value": next_ledger,
    }
    submission = begin_submission(
        package_root=scope.package_root,
        branch_id=scope.branch_id,
        requested_sequence=submission_sequence,
        logical_identity={
            "kind": "advance_receipt",
            "attempt_id": attempt_id,
            "status": "accepted",
            "component_ids": receipt["report_components"],
        },
        payload={
            "operations": operations,
            "ledger_hash": sidecar["next_hash"],
        },
        sidecars=[sidecar],
    )
    write_ledger(scope.package_root, scope.branch_id, next_ledger)
    if submission.phase not in {"published", "finalized"}:
        apply_batch(
            package_root=scope.package_root,
            branch_id=scope.branch_id,
            operations=operations,
            include_snapshot=False,
            submission=submission,
        )
    # The Profile-bound scope was resolved before the server mutation. Reuse
    # that exact identity for the local receipt so a successful transition is
    # not stranded by a second lookup against stale or historical bindings.
    report_scope = BranchReportScope(
        client_root=scope.client_root,
        profile_id=scope.profile_id,
        profile=scope.profile,
        record=scope.record,
        work_package_id=scope.record["record_id"],
        branch_id=scope.branch_id,
        package_root=scope.package_root,
        graph_branch_ref=(
            f"graph-branch:{scope.instance_id}:{scope.branch_id}"
        ),
    )
    authoring = (
        None if submission.phase == "finalized"
        else load_current_authoring(report_scope)
    )
    finalized = finalize_report_command(
        scope=report_scope,
        submission=submission,
        descriptor=authoring["descriptor"] if authoring else {},
        message="Accept research Graph advance",
        as_json=True,
    )
    _reconciliation_path(
        scope.package_root, scope.branch_id,
    ).unlink(missing_ok=True)
    return {
        "receipt": receipt,
        "report_components": receipt["report_components"],
        "git": finalized["git"],
    }


def require_complete_coverage(
    prepared: PreparedObligationAdvance,
) -> None:
    missing = [
        str(item["requirement_id"])
        for item in prepared.coverage_submission["coverage"]
        if item["edge_required"]
        and item["satisfaction"] not in _PASSING_COVERAGE
    ]
    if missing:
        raise ValueError(
            "selected edge has missing obligation coverage: "
            + ", ".join(missing)
        )


def _coverage_submission(
    *,
    ledger: dict[str, Any],
    edge_id: str,
    selected: dict[str, Any],
    coverage: list[dict[str, Any]],
) -> dict[str, Any]:
    value = {
        "schema_version": 1,
        "branch_ref": ledger["branch"]["branch_ref"],
        "graph_ref": ledger["branch"]["graph_ref"],
        "current_node": ledger["branch"]["current_node"],
        "context_ref": ledger["branch"]["context_ref"],
        "checkpoint_ref": ledger["branch"]["checkpoint_ref"],
        "edge_id": edge_id,
        "target_node": selected["target_node"],
        "coverage": coverage,
    }
    value["coverage_hash"] = "sha256:" + hashlib.sha256(
        _canonical_bytes(value)
    ).hexdigest()
    return value


def _bind_assessment_coverage(
    assessments: Any,
    coverage: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    node_coverage = [
        item for item in coverage if item.get("node_required") is True
    ]
    if not node_coverage and assessments is None:
        return []
    if not isinstance(assessments, list):
        raise ValueError("entry_requirement_assessments are required")
    by_id = {
        str(item.get("requirement_id") or ""): deepcopy(item)
        for item in assessments if isinstance(item, dict)
    }
    if len(by_id) != len(assessments):
        raise ValueError("entry requirement assessments must be unique objects")
    expected = {
        str(item["requirement_id"]) for item in node_coverage
    }
    if set(by_id) != expected:
        raise ValueError(
            "entry requirement assessments do not match current requirements"
        )
    result = []
    for row in node_coverage:
        requirement_id = str(row["requirement_id"])
        assessment = by_id[requirement_id]
        refs = list(row["obligation_refs"])
        if refs:
            assessment["coverage"] = {
                "decision": "map_existing",
                "obligation_refs": refs,
            }
        else:
            current = assessment.get("coverage") or {}
            if current.get("decision") != "no_material_issue":
                raise ValueError(
                    f"{requirement_id} has no mapped obligation; use an "
                    "accepted obligation change or explicitly assess "
                    "no_material_issue"
                )
            assessment["coverage"] = {
                "decision": "no_material_issue",
                "obligation_refs": [],
            }
        result.append(assessment)
    return result


def _pending_research_cycle(
    ledger: dict[str, Any],
) -> dict[str, Any] | None:
    accepted_sequence = max([
        int(item["sequence"])
        for item in ledger["history"]
        if item.get("event_type") == "advance_receipt"
        and item.get("status") == "accepted"
    ], default=0)
    values = [
        item.get("research_cycle")
        for item in ledger["history"]
        if item.get("event_type") == "obligation_change"
        and int(item["sequence"]) > accepted_sequence
    ]
    values = [item for item in values if isinstance(item, dict)]
    if not values:
        return None
    first = deepcopy(values[0])
    events: list[dict[str, Any]] = []
    parent = first.get("parent_trace_ref")
    for index, value in enumerate(values):
        if value.get("schema_version") != 1:
            raise ValueError("ledger research_cycle schema_version is invalid")
        if value.get("parent_trace_ref") != parent:
            raise ValueError("ledger research_cycle parent trace is inconsistent")
        current = value.get("events")
        if not isinstance(current, list) or any(
            not isinstance(item, dict) for item in current
        ):
            raise ValueError("ledger research_cycle events are invalid")
        if index and value.get("initial_checkpoint") is not None:
            raise ValueError(
                "only the first pending research_cycle may initialize"
            )
        events.extend(deepcopy(current))
    first["events"] = events
    return first


def _validate_selection(
    selected: Any,
    *,
    edge_packet: dict[str, Any],
    edge_id: str,
) -> None:
    if not isinstance(selected, dict):
        raise ValueError(
            "node advance requires research-graph edge choose first"
        )
    edge = edge_packet.get("edge") or {}
    edge_requirement_ids = [
        str(item["requirement_id"])
        for item in edge.get("obligation_requirements") or []
        if isinstance(item, dict) and item.get("requirement_id")
    ]
    if (
        selected.get("edge_id") != edge_id
        or selected.get("target_node") != str(edge.get("to_node") or "")
        or selected.get("state_ref")
        != str(edge_packet.get("state_ref") or "")
        or list(selected.get("required_requirement_ids") or [])
        != edge_requirement_ids
    ):
        raise ValueError(
            "selected edge is stale; choose the current edge again"
        )


def _wire_coverage(
    coverage: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {field: deepcopy(item[field]) for field in _WIRE_COVERAGE_FIELDS}
        for item in coverage
    ]


def _unreceipted_prepared(
    ledger: dict[str, Any],
) -> dict[str, Any] | None:
    receipts = {
        str(item.get("attempt_id") or "")
        for item in ledger["history"]
        if item.get("event_type") == "advance_receipt"
    }
    return next((
        item for item in reversed(ledger["history"])
        if item.get("event_type") == "advance_prepared"
        and str(item.get("attempt_id") or "") not in receipts
    ), None)


def _receipt_for(
    ledger: dict[str, Any],
    attempt_id: str,
) -> dict[str, Any] | None:
    return next((
        item for item in reversed(ledger["history"])
        if item.get("event_type") == "advance_receipt"
        and item.get("attempt_id") == attempt_id
    ), None)


def _git_head(package_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(package_root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _reconciliation_path(package_root: Path, branch_id: str) -> Path:
    branch = safe_package_component(branch_id, field="branch_id")
    return (
        Path(package_root) / "branches" / branch
        / "advance-reconciliation.json"
    )


def _event_id(seed: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        seed.encode() + b"\0" + _canonical_bytes(payload)
    ).hexdigest()[:32]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode()
