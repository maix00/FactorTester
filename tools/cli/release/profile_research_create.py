"""Profile-scoped Work Package creation.

The helper deliberately performs all local checks before the single server
write.  The server graph-instance transaction creates the Work Package and
its primary Hypothesis Branch together.
"""

from __future__ import annotations

import time
from typing import Any

from tools.cli.capability_projection import server_capability_resolution
from tools.cli.client import FactorTesterClient
from tools.cli.http import HttpSession

from .local_profile import LocalProfileStore
from .profile_research_context import ProfileResearchContext


def create_profile_research(
    store: LocalProfileStore,
    context: ProfileResearchContext,
    *,
    title: str,
    graph_id: str = "factor-research",
    product_group: str = "china_futures",
    capability_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one Profile-owned Work Package and its initial Branch."""
    title = title.strip()
    if not title:
        raise ValueError("title is required")
    client = FactorTesterClient(
        HttpSession(context.profile["server"]["base_url"])
    )
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
    branch_id = str((branches[0] if branches else {}).get("branch_id") or "")
    if not branch_id:
        raise ValueError("server returned a research without its primary Branch")
    now = time.time()
    work_package_id = str(instance.get("work_package_id") or instance.get("instance_id") or "")
    record = {
        "record_id": work_package_id,
        "title": title,
        "status": "pending",
        "scope": {
            "profile_id": context.profile_id,
            "product_group": product_group,
            "graph_id": graph_id,
            "agent_id": context.agent_id,
        },
        "factor_family_versions": [],
        "agent_id": context.agent_id,
        "created_at": now,
        "updated_at": now,
        "workspace_ref": context.workspace_ref,
        "run_ref": "",
        "graph_instance_ref": f"graph-instance:{instance.get('instance_id')}",
        "graph_branch_ref": f"graph-branch:{branch_id}",
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
    store.upsert_research_record(context.profile_id, record)
    return {
        "profile_id": context.profile_id,
        "profile_ref": context.profile_ref,
        "agent_id": context.agent_id,
        "workspace_ref": context.workspace_ref,
        "title": title,
        "research": instance,
        "local_record": record,
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
