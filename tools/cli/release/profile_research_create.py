"""Profile-scoped Work Package creation.

The helper deliberately performs all local checks before the single server
write.  The server graph-instance transaction creates the Work Package and
its primary Hypothesis Branch together.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from tools.cli.capability_projection import server_capability_resolution
from tools.cli.core.context import client_from_config

from .local_profile import LocalProfileStore
from .profile_research_context import ProfileResearchContext
from .research_reporting.authoring import (
    commit_branch_authoring,
    ensure_branch_authoring,
)
from .research_reporting.workspace import initialize_work_package


def create_profile_research(
    store: LocalProfileStore,
    context: ProfileResearchContext,
    *,
    title: str,
    graph_id: str = "factor-research",
    product_group: str | None = None,
    capability_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one Profile-owned Work Package and its initial Branch."""
    title = title.strip()
    if not title:
        raise ValueError("title is required")
    product_group = (product_group or "").strip()
    if not product_group:
        raise ValueError(
            "product_group is required; exact product universe belongs to the TrialPlan"
        )
    client = client_from_config()
    graph = client.get_active_research_graph(graph_id)
    resolution = capability_resolution or _default_resolution(graph)
    resolution = server_capability_resolution(resolution)
    instance = client.create_research_graph_instance(
        graph_id=graph_id,
        product_group=product_group,
        workspace_id=context.workspace_id,
        capability_resolution=resolution,
        profile_ref=context.profile_ref,
        title=title,
    )
    branches = instance.get("branches") or []
    primary_branch = branches[0] if branches else {}
    branch_id = str(primary_branch.get("branch_id") or "")
    if not branch_id:
        raise ValueError("server returned a research without its primary Branch")
    now = time.time()
    instance_id = str(instance.get("instance_id") or "")
    work_package_id = str(
        instance.get("work_package_id") or instance_id
    )
    branch_instance_id = str(
        primary_branch.get("instance_id") or instance_id
    )
    if not instance_id or not work_package_id or not branch_instance_id:
        raise ValueError(
            "server returned a research without canonical instance references"
        )
    record = {
        "record_id": work_package_id,
        "title": title,
        "status": "pending",
        "scope": {
            "profile_id": context.profile_id,
            "product_group": product_group,
            "product_scope_kind": "implementation_product_group",
            "product_universe_defined_in": "trial_plan",
            "graph_id": graph_id,
            "agent_id": context.agent_id,
        },
        "factor_family_versions": [],
        "agent_id": context.agent_id,
        "created_at": now,
        "updated_at": now,
        "workspace_ref": context.workspace_ref,
        "run_ref": "",
        "graph_instance_ref": f"work-package:{work_package_id}",
        "graph_branch_ref": (
            f"graph-branch:{branch_instance_id}:{branch_id}"
        ),
        "branch_bindings": [{
            "branch_ref": (
                f"graph-branch:{branch_instance_id}:{branch_id}"
            ),
            "kind": "live",
            "source_branch_ref": "",
        }],
        "checkpoint_ref": "",
        "evidence_refs": [],
        "artifacts": [],
        "provenance": {
            "created_by": "factortester client research create",
            "profile_ref": context.profile_ref,
            "factor_worktree_ref": str(
                context.profile["factor_workspace_binding"].get("receipt_ref") or ""
            ),
        },
        "timeline_refs": [],
    }
    report = initialize_work_package(
        workspace_root=Path(context.profile["workspace_root"]),
        work_package_id=work_package_id,
        branch_id=branch_id,
        workspace_id=context.workspace_id,
        title=title,
        branch_ref=record["graph_branch_ref"],
        factor_family_versions=record["factor_family_versions"],
    )
    authoring = ensure_branch_authoring(
        package_root=report["package_root"],
        work_package_id=work_package_id,
        branch_id=branch_id,
        title=title,
        branch_ref=record["graph_branch_ref"],
        node_id=str(graph.get("entry_node") or ""),
        commit=False,
    )
    authoring_git = commit_branch_authoring(
        report["package_root"],
        message="Create initial research report chapter",
    )
    record["artifacts"] = [report["descriptor"], authoring["descriptor"]]
    store.upsert_research_record(context.profile_id, record)
    return {
        "profile_id": context.profile_id,
        "profile_ref": context.profile_ref,
        "agent_id": context.agent_id,
        "workspace_ref": context.workspace_ref,
        "title": title,
        "research": instance,
        "local_record": record,
        "local_report": {
            "path": str(report["head_path"]),
            "git": authoring_git,
            "authoring_path": str(authoring["paths"]["head"]),
        },
    }


def _default_resolution(graph: dict[str, Any]) -> dict[str, Any]:
    entry_node = str(graph.get("entry_node") or "")
    node = next(
        (item for item in graph.get("nodes") or []
         if str(item.get("node_id") or "") == entry_node),
        None,
    )
    if node is None:
        raise ValueError("active Graph has no valid entry node")
    descriptors = graph.get("capability_descriptors") or {}
    bindings = []
    for capability_id in node.get("required_capabilities") or []:
        descriptor = descriptors.get(str(capability_id))
        if not isinstance(descriptor, dict):
            raise ValueError(
                f"active Graph has no descriptor for {capability_id}"
            )
        bindings.append({
            "capability_id": str(capability_id),
            "capability_description": descriptor.get("capability_description"),
            "descriptor_hash": descriptor.get("descriptor_hash"),
        })
    return {
        "node_id": entry_node,
        "bindings": bindings,
        "gaps": [],
        "triggered_conditional_bindings": [],
        "triggered_conditional_gaps": [],
        "undetermined_conditions": [],
    }
