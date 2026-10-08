"""Dispatch explicit report references to their authoritative owner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.cli.client import FactorTesterClient
from tools.cli.core.context import client_from_config
from tools.cli.release.local_profile import LocalProfileStore

from ..authoring.declared_links import DeclaredReportReference
from .run_authority import validate_run_reference
from .factor_formula import validate_factor_reference
from .factor_set_workspace import validate_factor_set_reference
from .profile_revisions import ProfileRevisionStore

_PRODUCT_KINDS = {"product", "contract", "continuous_contract"}


def validate_declared_reference(
    *,
    reference: DeclaredReportReference,
    scope: Any,
    client: FactorTesterClient | None = None,
    report_components: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate one declared kind/ref pair without rewriting either value."""
    kind, target_ref = reference.kind, reference.target_ref
    if kind == 'report_section':
        component_id = _suffix(target_ref, 'node:')
        if report_components is None:
            from ..authoring.tree_projection import load_snapshot
            snapshot = load_snapshot(package_root=scope.package_root, branch_id=scope.branch_id)
            report_components = {n['component_id']: n for n in snapshot['components']}
        node = report_components.get(component_id)
        if node is None:
            raise ValueError('report section reference does not exist in the target branch')
        data = {'component_id': component_id, 'title': str(node.get('title') or ''),
                'kind': str(node.get('kind') or ''), 'branch_id': scope.branch_id}
    elif kind == "factor":
        validator = (
            validate_factor_set_reference
            if target_ref.startswith("factor-set:")
            else validate_factor_reference
        )
        data = validator(kind=kind, target_ref=target_ref, roots=_factor_roots(scope))
        if data.get("object_class") == "FactorSet":
            data = {
                key: value for key, value in data.items()
                if key not in {"member_refs", "related_references", "descriptor"}
            }
            data["member_resolution"] = {
                "owner": "client_cli",
                "strategy": "paged_manifest",
                "default_page_size": 50,
            }
    elif kind == "profile":
        profile_id = _suffix(target_ref, "profile:")
        profile = LocalProfileStore(scope.client_root).load(profile_id)
        data = {
            "profile_id": profile_id,
            "display_name": str(profile["display_name"]),
            "status": str(profile["status"]),
        }
    elif kind == "profile_revision":
        snapshot = ProfileRevisionStore(scope.client_root).load(target_ref)
        data = {
            "profile_id": str(snapshot["profile_id"]),
            "configuration_hash": target_ref.rsplit(":", 1)[-1],
            "configuration": snapshot["configuration"],
        }
    elif kind in _PRODUCT_KINDS:
        validated = _client(scope, client).validate_report_reference(
            kind=kind, target_ref=target_ref,
        )
        _assert_unchanged(reference, validated)
        data = dict(validated.get("object") or {})
    elif kind == "evidence":
        evidence = _client(scope, client).get_research_evidence(target_ref)
        if evidence.get("evidence_ref") != target_ref:
            raise ValueError("evidence authority did not return the exact reference")
        data = _bounded_metadata(evidence)
    elif kind == "job":
        job_id = _suffix(target_ref, "job:")
        job = _client(scope, client).get_job(job_id)
        if str(job.get("job_id") or "") != job_id:
            raise ValueError("Job authority did not return the exact reference")
        data = _bounded_metadata(job)
    elif kind in {"run", "run_spec", "trial_plan"}:
        data = validate_run_reference(
            reference=reference,
            client=_client(scope, client),
        )
    else:
        raise ValueError(
            f"Agent-authored report reference kind has no authority: {kind}"
        )
    return {
        "kind": kind,
        "target_ref": target_ref,
        "label": reference.label,
        "data": data,
    }


def _factor_roots(scope: Any) -> dict[str, Path]:
    profile = scope.profile
    binding = profile.get("factor_workspace_binding") or {}
    roots: dict[str, Path] = {}
    worktree = str(binding.get("worktree_path") or "")
    if worktree:
        roots[f"profile-{scope.profile_id}"] = Path(worktree)
    workspace_root = Path(str(profile.get("workspace_root") or ""))
    if len(workspace_root.parents) >= 2:
        roots["personal"] = (
            workspace_root.parents[1]
            / "personal-workspace" / "factor-library"
        )
    return roots


def _client(scope: Any, supplied: FactorTesterClient | None) -> FactorTesterClient:
    if supplied is not None:
        return supplied
    return client_from_config()


def _assert_unchanged(
    reference: DeclaredReportReference, validated: dict[str, Any],
) -> None:
    if (
        validated.get("kind") != reference.kind
        or validated.get("target_ref") != reference.target_ref
    ):
        raise ValueError("reference authority rewrote the Agent-authored object")


def _suffix(value: str, prefix: str) -> str:
    if not value.startswith(prefix) or value == prefix:
        raise ValueError(f"reference must start with {prefix}")
    return value.removeprefix(prefix)


def _bounded_metadata(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "evidence_ref", "evidence_kind", "created_at", "job_id", "status",
        "kind", "submitted_at", "started_at", "finished_at", "port",
    }
    return {key: value[key] for key in allowed if key in value}
