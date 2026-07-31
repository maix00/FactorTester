"""Local report publication for one live Graph continuation."""

from __future__ import annotations

from pathlib import Path

from tools.cli.client import FactorTesterClient
from tools.cli.release.research_reporting.continuation_narrative import (
    continuation_narrative,
)
from tools.cli.release.research_reporting.publisher import (
    publish_research_checkpoint,
)

from .research_graph_continuation_parent import (
    prepare_continuation_report_parent,
)


def publish_continuation_report(
    *,
    client: FactorTesterClient,
    client_root: Path,
    profile_id: str,
    agent_id: str,
    work_package_id: str,
    source_work_package_id: str,
    source_branch_id: str,
    target_instance_id: str,
    target_branch_id: str,
) -> dict[str, object]:
    """Inherit and publish one server-created continuation checkpoint."""
    try:
        parent = prepare_continuation_report_parent(
            client=client, client_root=client_root,
            profile_id=profile_id, agent_id=agent_id,
            work_package_id=work_package_id,
            source_work_package_id=source_work_package_id,
            source_branch_id=source_branch_id,
            target_instance_id=target_instance_id,
            target_branch_id=target_branch_id,
        )
        branch = client.get_profile_research_branch(
            f"work-package:{work_package_id}", target_branch_id,
        )
        carrier = branch.get("report_checkpoint")
        if not isinstance(carrier, dict):
            raise ValueError("continuation report Carrier is unavailable")
        published = publish_research_checkpoint(
            client_root=client_root,
            profile_id=profile_id,
            agent_id=agent_id,
            carrier=carrier,
            narrative=continuation_narrative(carrier),
            report_parent_id=str(parent["component_id"]),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return {
            "status": "required",
            "error_code": (
                "local_report_io_error"
                if isinstance(exc, OSError)
                else "local_report_validation_error"
            ),
            "message": str(exc),
        }
    artifact = published["artifact"]
    return {
        "status": "published",
        "changed": published["changed"],
        "checkpoint_ref": published["checkpoint_ref"],
        "artifact_ref": artifact["artifact_ref"],
        "report_parent_id": parent["component_id"],
    }
