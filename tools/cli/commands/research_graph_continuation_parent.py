"""Resolve the server-owned report parent for one Graph continuation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.cli.client import FactorTesterClient
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.research_reporting.authoring.tree_fork import (
    inherit_continuation_report_tree,
)

from .research_graph_chapter_reconciliation import (
    synchronize_transition_container,
)
from .research_graph_continuation_validation import (
    require_existing_anchor,
    validate_parent,
)
from .research_graph_local_report import resolve_local_graph_report
from .research_graph_report_policy import report_container


def prepare_continuation_report_parent(
    *,
    client: FactorTesterClient,
    client_root: Path,
    profile_id: str,
    agent_id: str,
    work_package_id: str,
    source_branch_id: str,
    target_instance_id: str,
    target_branch_id: str,
) -> dict[str, Any]:
    """Inherit history, then resolve the exact top server container."""
    profile = LocalProfileStore(client_root).load(profile_id)
    package_root = (
        Path(profile["workspace_root"]).expanduser()
        / "research" / work_package_id
    )
    inherited = inherit_continuation_report_tree(
        package_root=package_root,
        source_branch_id=source_branch_id,
        target_branch_id=target_branch_id,
        target_report_id=f"report-{work_package_id}-{target_branch_id}",
    )
    scope = resolve_local_graph_report(
        client_root=client_root, profile_id=profile_id,
        agent_id=agent_id, instance_id=target_instance_id,
        branch_id=target_branch_id,
    )
    packet = client.get_research_graph_node_info(
        target_instance_id, target_branch_id,
    )
    container = report_container(packet)
    require_existing_anchor(scope.package_root, target_branch_id, container)
    synchronized = synchronize_transition_container(
        scope, container=container,
    )
    validate_parent(
        scope.package_root, target_branch_id,
        str(synchronized["component_id"]), container,
    )
    return {
        "component_id": synchronized["component_id"],
        "container": container,
        "inherited": inherited["inherited"],
        "synchronized": synchronized,
    }
