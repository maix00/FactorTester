"""Cold-path server evidence for the authoritative backtest transition."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

import settings as Settings
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus
from server.services.research_graph.branch.repository import (
    load_instance_branch_with_latest_trace,
)
from server.services.research_graph.branch.research_cycle import (
    checkpoint_from_branch_row,
)
from server.services.research_graph.research_cycle.job_evidence import (
    project_job_attempt_evidence,
)
from server.services.research_evidence_catalog import (
    capture_job_source,
    create_evidence,
    put_source_fragment,
)
from server.services.research_evidence_catalog.validation import digest
from server.services.research_graph.versions import load_graph_from_conn
from tools.data.sqlite.db import connect_sqlite


SERVER_ACTION = "bind_job_attempt"
REQUEST_FIELD = "job_attempt_request"
_SERVER_GUARDS = (
    "terminal_job_evidence_retained",
    "terminal_job_trusted",
    "net_return_series_available",
)


def persist_terminal_job_evidence(
    *,
    detail: dict[str, Any],
    owner: str,
) -> dict[str, Any] | None:
    """Register a trusted terminal JobAttempt as reusable evidence.

    Job completion owns factual registration.  Report writing remains local to
    the Profile client, while the server keeps only the content-addressed
    envelope and its applicability scope.
    """
    job = detail.get("job")
    binding = detail.get("trial_binding") or {}
    if job is None or not isinstance(binding, dict):
        return None
    envelope = project_job_attempt_evidence(
        job,
        identity_refs=detail.get("identity_refs"),
        trial_stage=str(binding.get("trial_stage") or ""),
        active_artifacts=detail.get("active_artifacts") or [],
    )
    if envelope is None:
        return None
    identity = envelope.get("identity_refs") or {}
    applicability = _job_applicability(detail)
    for field in (
        "contract_hash", "methodology_hash", "trial_plan_hash",
        "run_spec_hash",
    ):
        value = str(identity.get(field) or "")
        if value:
            applicability[field] = value
    source = capture_job_source(owner=owner, job_id=job.job_id)
    fragments = []
    for item in source.pop("available_fragments", []):
        preview = item.get("preview") or {}
        fragments.append(put_source_fragment(
            owner=owner,
            source_ref=source["source_ref"],
            selector=item["selector"],
            fragment_hash=digest(preview),
            title_zh=str(item["title_zh"]),
            summary_zh=_job_fragment_summary(item),
            preview=preview,
        ))
    if not fragments:
        return None
    return create_evidence(
        owner=owner,
        evidence_kind="authoritative_backtest",
        fragment_refs=[item["fragment_ref"] for item in fragments],
        title_zh="终态回测结果",
        description_zh="由服务端终态任务及其结果片段形成的规范回测证据",
        claim_summary="该任务在冻结身份下完成并产生所列终态结果",
        applicability=applicability,
        identity_refs=identity,
        limitations=list(envelope.get("limitations") or []),
        conflicts=list(envelope.get("conflicts") or []),
    )


def _job_applicability(detail: dict[str, Any]) -> dict[str, Any]:
    """Project only explicit, frozen Job scope fields into Evidence scope."""
    job = detail["job"]
    spec = job.job_spec if isinstance(job.job_spec, dict) else {}
    identity = detail.get("identity_refs") or {}
    applicability: dict[str, Any] = {
        "source_refs": [
            f"research-job:{job.job_id}",
            f"research-run:{job.run_id}",
        ],
    }
    trial_binding = detail.get("trial_binding") or {}
    sample_ref = str(trial_binding.get("sample_ref") or "").strip()
    if sample_ref:
        applicability["sample_refs"] = [sample_ref]
    product_refs = _job_product_refs(spec)
    if product_refs:
        applicability["product_refs"] = product_refs
    factor_refs = _job_factor_refs(spec)
    if factor_refs:
        applicability["factor_refs"] = factor_refs
    time_window = _job_time_window(spec)
    if time_window is not None:
        applicability["time_window"] = time_window
    for field in (
        "contract_hash", "methodology_hash", "trial_plan_hash",
        "run_spec_hash",
    ):
        value = str(identity.get(field) or "")
        if value:
            applicability[field] = value
    return applicability


def _job_product_refs(spec: dict[str, Any]) -> list[str]:
    refs: set[str] = set()
    for value in _walk_objects(spec):
        products = value.get("products")
        if isinstance(products, list):
            for product in products:
                name = (
                    str(product.get("name") or "").strip()
                    if isinstance(product, dict) else ""
                )
                if name:
                    refs.add(f"product:{name}")
        paths = value.get("selected_paths")
        if isinstance(paths, list):
            for path in paths:
                text = str(path or "")
                marker = "/_products/"
                if marker in text:
                    refs.add("product:" + text.rsplit(marker, 1)[1])
    return sorted(refs)


def _job_factor_refs(spec: dict[str, Any]) -> list[str]:
    aliases: set[str] = set()
    for value in _walk_objects(spec):
        for key in ("alias", "factorAlias", "factor"):
            alias = str(value.get(key) or "").strip()
            if alias and ("|" in alias or key != "alias"):
                aliases.add(alias)
    manifests = spec.get("factor_revision_manifests")
    if not isinstance(manifests, list):
        manifests = (
            (spec.get("run_spec") or {})
            .get("configuration", {})
            .get("shared", {})
            .get("factor_revision_manifests", [])
            if isinstance(spec.get("run_spec"), dict) else []
        )
    aliases_by_hash = {
        hashlib.sha256(alias.encode()).hexdigest(): alias
        for alias in aliases
    }
    refs: set[str] = set()
    unresolved: list[str] = []
    for item in manifests:
        if not isinstance(item, dict):
            continue
        alias = aliases_by_hash.get(str(item.get("factor_alias_hash") or ""))
        revision = str(
            item.get("resolved_factor_expr_hash")
            or item.get("manifest_hash") or ""
        ).strip().removeprefix("sha256:")
        if alias and len(revision) == 64 and all(
            char in "0123456789abcdef" for char in revision
        ):
            refs.add(f"factor-expr:{alias}@sha256:{revision}")
        elif len(revision) == 64 and all(
            char in "0123456789abcdef" for char in revision
        ):
            unresolved.append(revision)
    if not refs and len(aliases) == 1 and len(unresolved) == 1:
        # Historical single-factor JobSpecs predate factor_alias_hash.  A
        # one-to-one binding is still unambiguous; multi-factor specs fail
        # closed instead of inventing an alias x revision Cartesian product.
        refs.add(
            f"factor-expr:{next(iter(aliases))}@sha256:{unresolved[0]}"
        )
    refs.update(_job_factor_set_refs(spec))
    return sorted(refs)


def _job_factor_set_refs(spec: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for value in _walk_objects(spec):
        candidates: list[Any] = []
        if "factor_set_ref" in value:
            candidates.append(value.get("factor_set_ref"))
        if isinstance(value.get("factor_set_refs"), list):
            candidates.extend(value["factor_set_refs"])
        descriptors = value.get("factor_subject_descriptors")
        if isinstance(descriptors, list):
            candidates.extend(
                item.get("target_ref")
                for item in descriptors
                if isinstance(item, dict)
            )
        for candidate in candidates:
            text = str(candidate or "").strip()
            parts = text.split(":")
            if (
                len(parts) == 7
                and parts[:2] == ["factor-set", "v1"]
                and len(parts[-2]) in {40, 64}
                and len(parts[-1]) in {40, 64}
                and all(char in "0123456789abcdef" for char in parts[-2])
                and all(char in "0123456789abcdef" for char in parts[-1])
            ):
                refs.add(text)
    return refs


def _job_time_window(spec: dict[str, Any]) -> dict[str, str] | None:
    windows = {
        (
            str(value.get("start_date") or "").strip(),
            str(value.get("end_date") or "").strip(),
        )
        for value in _walk_objects(spec)
        if value.get("start_date") and value.get("end_date")
    }
    if len(windows) != 1:
        return None
    start, end = next(iter(windows))
    return {"start": start, "end": end}


def _walk_objects(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_objects(child)


def _job_fragment_summary(item: dict[str, Any]) -> str:
    selector = item.get("selector") or {}
    if "artifact_ref" in selector:
        return "任务生成物的冻结身份与内容哈希"
    if selector.get("field") == "status":
        return "任务完成后的规范终态字段"
    if selector.get("json_pointer") == "/terminal_assurance":
        return "任务完成时由服务端生成的终态校验摘要"
    return "任务完成后由服务端冻结的结果摘要"


def prepare_transition(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
    edge_id: str,
    request: Any,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if request is None:
        return None
    job_id = _request_job_id(request)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        row = load_instance_branch_with_latest_trace(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            owner=owner,
        )
        if row is None:
            raise KeyError("graph branch not found")
        graph = load_graph_from_conn(
            conn,
            graph_id=str(row["graph_id"]),
            version=int(row["graph_version"]),
        ) or {}
        edge = _edge(graph, edge_id)
        _validate_edge(row=row, edge=edge)
        checkpoint = checkpoint_from_branch_row(row)
        if checkpoint is None:
            raise ValueError(
                "JobAttempt evidence requires a Research Cycle checkpoint"
            )
        expected = branch_identity(row)
    return prepare_bound_job_evidence(
        job_id=job_id,
        owner=owner,
        checkpoint=checkpoint,
        expected=expected,
    )


def prepare_bound_job_evidence(
    *,
    job_id: str,
    owner: str,
    checkpoint: dict[str, Any],
    expected: dict[str, Any],
) -> dict[str, Any]:
    """Project one source-bound Job without changing its Graph identity."""
    detail = JobRepository(Settings.CACHE_DB_PATH).load_detail(
        job_id,
        owner=owner,
    )
    if detail is None:
        raise KeyError("research job not found")
    _validate_binding(
        detail=detail,
        checkpoint=checkpoint,
        expected=expected,
    )
    envelope = project_job_attempt_evidence(
        detail["job"],
        identity_refs=detail["identity_refs"],
        trial_stage=str(detail["trial_binding"]["trial_stage"]),
        active_artifacts=detail["active_artifacts"],
    )
    if envelope is None:
        raise ValueError(
            "JobAttempt lacks terminal server assurance or immutable identity"
        )
    registered = persist_terminal_job_evidence(
        detail=detail,
        owner=owner,
    )
    if registered is None:
        raise ValueError("JobAttempt lacks fragment-bound terminal Evidence")
    facts = envelope["facts"]
    assurance = facts["assurance"]
    trusted = (
        detail["job"].status is JobStatus.SUCCEEDED
        and assurance["disposition"] == "trusted"
        and not assurance["anomaly_codes"]
    )
    return {
        "expected": expected,
        "guard_facts": {
            "terminal_job_evidence_retained": True,
            "terminal_job_trusted": trusted,
            "net_return_series_available": bool(
                facts["net_return_series_available"]
            ),
        },
        "envelope": envelope,
        "evidence_ref": registered["evidence_ref"],
    }


def bind_server_evidence(
    evidence: dict[str, Any],
    prepared: dict[str, Any] | None,
) -> dict[str, Any]:
    value = deepcopy(evidence)
    value.pop(REQUEST_FIELD, None)
    for field in _SERVER_GUARDS:
        value.pop(field, None)
    if prepared is None:
        return value
    value["server_evidence"] = {
        "job_attempt": deepcopy(prepared["envelope"]),
    }
    refs = value.get("evidence_refs", [])
    if not isinstance(refs, list) or not all(
        isinstance(item, str) and item for item in refs
    ):
        raise ValueError("evidence_refs must be a reference array")
    value["evidence_refs"] = list(dict.fromkeys([
        *refs,
        prepared["evidence_ref"],
    ]))
    return value


def validate_preflight(
    *,
    row: Any,
    edge: dict[str, Any],
    prepared: dict[str, Any] | None,
) -> None:
    if edge.get("server_action") == SERVER_ACTION and prepared is None:
        raise ValueError(
            "backtest transition requires job_attempt_request"
        )
    if prepared is None:
        return
    _validate_edge(row=row, edge=edge)
    if branch_identity(row) != prepared["expected"]:
        raise ValueError(
            "JobAttempt preflight is stale; inspect the current branch again"
        )


def _validate_binding(
    *,
    detail: dict[str, Any],
    checkpoint: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    job = detail["job"]
    binding = detail["trial_binding"]
    graph_binding = detail["graph_binding"]
    identity = detail["identity_refs"]
    if binding is None or graph_binding is None or identity is None:
        raise ValueError("JobAttempt lacks immutable TrialPlan identity")
    if job.workspace_id != expected["workspace_id"]:
        raise ValueError("JobAttempt workspace does not match Graph branch")
    if (
        graph_binding["instance_id"] != expected["instance_id"]
        or graph_binding["branch_id"] != expected["branch_id"]
    ):
        raise ValueError("JobAttempt does not belong to this Graph branch")
    required = {
        "contract_hash": checkpoint["contract_hash"],
        "methodology_hash": checkpoint["methodology_hash"],
        "trial_plan_hash": checkpoint["trial_plan_hash"],
    }
    if any(identity.get(key) != value for key, value in required.items()):
        raise ValueError(
            "JobAttempt Contract, Methodology, or TrialPlan is stale"
        )
    if identity["trial_plan_hash"] != expected["trial_plan_hash"]:
        raise ValueError("JobAttempt does not match the active TrialPlan")


def _request_job_id(value: Any) -> str:
    if not isinstance(value, dict) or set(value) != {"job_id"}:
        raise ValueError("job_attempt_request requires only job_id")
    job_id = value.get("job_id")
    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("job_attempt_request.job_id must be non-empty")
    return job_id.strip()


def branch_identity(row: Any) -> dict[str, Any]:
    return {
        "instance_id": str(row["instance_id"]),
        "branch_id": str(row["branch_id"]),
        "current_node": str(row["current_node"]),
        "latest_trace_id": str(row["latest_trace_id"]),
        "graph_id": str(row["graph_id"]),
        "graph_version": int(row["graph_version"]),
        "workspace_id": str(row["workspace_id"]),
        "trial_plan_hash": str(row["current_trial_plan_hash"]),
    }


def _validate_edge(*, row: Any, edge: dict[str, Any]) -> None:
    if edge.get("server_action") != SERVER_ACTION:
        raise ValueError("job_attempt_request is not allowed on this edge")
    if str(edge.get("from_node") or "") != str(row["current_node"]):
        raise ValueError("JobAttempt edge does not leave current node")


def _edge(graph: dict[str, Any], edge_id: str) -> dict[str, Any]:
    edge = next(
        (
            item for item in graph.get("edges") or []
            if str(item.get("edge_id") or "") == edge_id
        ),
        None,
    )
    if edge is None:
        raise KeyError("graph edge not found")
    return edge
