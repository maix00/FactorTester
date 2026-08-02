"""Validate Agent-declared references owned by one Research Graph branch."""

from __future__ import annotations

from typing import Any

from tools.cli.client import FactorTesterClient
from tools.cli.http import HttpClientError
from tools.cli.release.research_obligations import load_ledger

from ..authoring.declared_links import DeclaredReportReference


_CYCLE_FIELDS = {
    "claim": "claim_id",
    "obligation": "obligation_id",
    "task": "task_ref",
    "run": "run_id",
    "run_spec": "run_spec_hash",
    "trial_plan": "trial_plan_id",
}
_TIMELINE_FIELDS = {
    "trial_plan": "trial_plan_refs",
}


def validate_cycle_reference(
    *,
    reference: DeclaredReportReference,
    scope: Any,
    client: FactorTesterClient,
) -> dict[str, Any]:
    object_type = reference.kind
    object_id, trace_id = _object_identity(
        kind=object_type,
        target_ref=reference.target_ref,
    )
    if object_type == "trial_plan":
        try:
            direct = client.get_direct_trial_plan(reference.target_ref)
        except HttpClientError as error:
            if error.status != 404:
                raise
        else:
            if not _matches_exact_object(
                kind=object_type,
                object_id=object_id,
                value=direct,
            ):
                raise ValueError(
                    "direct TrialPlan authority did not return the exact reference"
                )
            return _bounded({
                **direct,
                "authority_scope": "direct_registry",
            })
    if object_type == "run":
        run = client.get_run(object_id)
        if not _matches_exact_object(
            kind=object_type,
            object_id=object_id,
            value=run,
        ):
            raise ValueError("Run authority did not return the exact reference")
        return _bounded({
            **run,
            "authority_scope": "owner_run_registry",
        })
    if object_type == "run_spec":
        run_spec = client.get_run_spec(object_id.removeprefix("sha256:"))
        if not _matches_exact_object(
            kind=object_type,
            object_id=object_id,
            value=run_spec,
        ):
            raise ValueError(
                "RunSpec authority did not return the exact reference"
            )
        return _bounded({
            **run_spec,
            "authority_scope": "owner_run_spec_registry",
        })
    instance_id, branch_id = _graph_branch(scope)
    if object_type == "obligation":
        local = _local_obligation(scope=scope, obligation_id=object_id)
        if local is not None:
            return _bounded(local)
    trace_id = (
        _trace_for_reference(
            client=client,
            scope=scope,
            target_ref=reference.target_ref,
            field=_TIMELINE_FIELDS[object_type],
        )
        if object_type in _TIMELINE_FIELDS else trace_id
    )
    value = client.get_research_cycle_object(
        instance_id,
        branch_id,
        object_type,
        object_id,
        trace_id=trace_id,
    )
    if not _matches_exact_object(
        kind=object_type,
        object_id=object_id,
        value=value,
    ):
        raise ValueError(
            "research cycle authority did not return the exact reference"
        )
    return _bounded({
        **value,
        "authority_scope": (
            "research_graph_timeline"
            if object_type in _TIMELINE_FIELDS
            else "research_graph_cycle"
        ),
    })


def _local_obligation(
    *, scope: Any, obligation_id: str,
) -> dict[str, Any] | None:
    """Resolve the branch-owned durable obligation before remote projection."""
    package_root = getattr(scope, "package_root", None)
    branch_id = str(getattr(scope, "branch_id", "") or "")
    if package_root is None or not branch_id:
        return None
    try:
        ledger = load_ledger(package_root, branch_id)
    except (FileNotFoundError, OSError, ValueError):
        return None
    candidates = list(
        (ledger.get("current_projection") or {}).get("obligations") or []
    )
    for event in reversed(ledger.get("history") or []):
        candidates.extend(event.get("obligations_snapshot") or [])
    for value in candidates:
        if (
            isinstance(value, dict)
            and str(value.get("obligation_id") or "") == obligation_id
        ):
            return dict(value)
    return None


def _graph_branch(scope: Any) -> tuple[str, str]:
    reference = str(getattr(scope, "branch_ref", "") or "")
    parts = reference.split(":")
    if (
        len(parts) != 3
        or parts[0] != "graph-branch"
        or not parts[1]
        or not parts[2]
    ):
        raise ValueError(
            "Agent-authored cycle reference requires an explicit graph branch"
        )
    return parts[1], parts[2]


def _object_identity(*, kind: str, target_ref: str) -> tuple[str, str | None]:
    prefix = {
        "claim": "claim:",
        "obligation": "obligation:",
    }.get(kind)
    if prefix:
        if not target_ref.startswith(prefix) or target_ref == prefix:
            raise ValueError(f"{kind} reference must start with {prefix}")
        return target_ref.removeprefix(prefix), None
    if kind == "task":
        if not target_ref.strip():
            raise ValueError("task reference is empty")
        return target_ref, None
    if kind == "run":
        return _prefixed(target_ref, "run:", kind), None
    if kind == "run_spec":
        value = _prefixed(target_ref, "runspec:sha256:", kind)
        return "sha256:" + value, None
    if kind == "trial_plan":
        return _prefixed(target_ref, "trial-plan:", kind), None
    raise ValueError(f"unsupported research cycle reference kind: {kind}")


def _trace_for_reference(
    *,
    client: FactorTesterClient,
    scope: Any,
    target_ref: str,
    field: str,
) -> str:
    work_package_id = str(getattr(scope, "work_package_id", "") or "")
    branch_id = str(getattr(scope, "branch_id", "") or "")
    if not work_package_id or not branch_id:
        raise ValueError(
            "historical object authority requires Work Package and branch scope"
        )
    after = ""
    seen: set[str] = set()
    while True:
        page = client.list_profile_research_branch_timeline(
            f"work-package:{work_package_id}",
            branch_id,
            limit=50,
            after=after,
        )
        items = page.get("items")
        if not isinstance(items, list):
            raise ValueError("research timeline authority returned invalid items")
        for item in items:
            if (
                isinstance(item, dict)
                and target_ref in (item.get(field) or [])
            ):
                step_ref = str(item.get("step_ref") or "")
                if step_ref.startswith("trace:") and len(step_ref) > 6:
                    return step_ref.removeprefix("trace:")
                raise ValueError(
                    "research timeline authority returned an invalid trace"
                )
        cursor = str(page.get("next_cursor") or "")
        if not cursor:
            break
        if cursor in seen:
            raise ValueError("research timeline authority cursor repeated")
        seen.add(cursor)
        after = cursor
    raise KeyError("research timeline does not contain the exact reference")


def _matches_exact_object(
    *,
    kind: str,
    object_id: str,
    value: dict[str, Any],
) -> bool:
    if kind == "trial_plan" and object_id.startswith("sha256:"):
        return str(value.get("trial_plan_hash") or "") == object_id.removeprefix(
            "sha256:"
        )
    expected = object_id.removeprefix("sha256:") if kind == "run_spec" else object_id
    return str(value.get(_CYCLE_FIELDS[kind]) or "") == expected


def _prefixed(target_ref: str, prefix: str, kind: str) -> str:
    if not target_ref.startswith(prefix) or target_ref == prefix:
        raise ValueError(f"{kind} reference must start with {prefix}")
    return target_ref.removeprefix(prefix)


def _bounded(value: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "schema_version", "object_kind", "claim_id", "claim_ref",
        "claim_type", "evidence_state", "obligation_id", "obligation_kind",
        "epistemic_question", "status", "materiality", "task_ref",
        "run_id", "run_spec_hash", "run_spec_version",
        "configuration_id", "configuration_revision",
        "trial_plan_id", "trial_plan_hash", "version",
        "alias_zh", "summary_zh",
        "title_zh", "authority_scope", "binding_origin", "trial_plan_ref",
        "requirement_refs", "claim_ids", "evidence_refs",
    }
    result = {key: value[key] for key in fields if key in value}
    related = _related_references(result)
    if related:
        result["related_references"] = related
    return result


def _related_references(value: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for field, relation, kind, prefix in (
        ("requirement_refs", "要求", "entry_requirement", "requirement:"),
        ("claim_ids", "关联主张", "claim", "claim:"),
        ("evidence_refs", "支持证据", "evidence", "evidence:"),
    ):
        for raw in value.get(field) or []:
            if not isinstance(raw, str) or not raw:
                continue
            target_ref = raw if raw.startswith(prefix) else prefix + raw
            result.append({
                "relation": relation,
                "kind": kind,
                "target_ref": target_ref,
                "label": raw.removeprefix(prefix),
                "data": {},
            })
    return result
