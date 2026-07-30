"""Retryable local report publication for one existing shadow continuation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from tools.cli.client import FactorTesterClient
from tools.cli.http import HttpSession
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.research_branch_bindings import binding_for
from tools.cli.release.profile import load_profile_root
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


def register_continuation_report_commands(parent: click.Group) -> None:
    """Register the explicit, server-idempotent local retry surface."""

    @parent.command("continuation-report-retry")
    @click.argument("target_instance_id")
    @click.argument("target_branch_id")
    @click.option("--profile-id", required=True)
    @click.option("--agent-id", required=True)
    @click.option(
        "--release-profile",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )
    def continuation_report_retry(
        target_instance_id: str,
        target_branch_id: str,
        profile_id: str,
        agent_id: str,
        release_profile: Path | None,
    ) -> None:
        """Retry only the local report for an existing shadow continuation."""
        client_root = load_profile_root(release_profile)
        source = shadow_continuation_source(
            client_root=client_root,
            profile_id=profile_id,
            agent_id=agent_id,
            target_instance_id=target_instance_id,
            target_branch_id=target_branch_id,
        )
        profile = LocalProfileStore(client_root).load(profile_id)
        client = FactorTesterClient(
            HttpSession(profile["server"]["base_url"])
        )
        result = publish_continuation_report(
            client=client,
            client_root=client_root,
            profile_id=profile_id,
            agent_id=agent_id,
            work_package_id=source["target_work_package_id"],
            source_work_package_id=source["source_work_package_id"],
            source_branch_id=source["source_branch_id"],
            target_instance_id=target_instance_id,
            target_branch_id=target_branch_id,
        )
        click.echo(json.dumps(
            result, ensure_ascii=False, indent=2, sort_keys=True,
        ))


def shadow_continuation_source(
    *,
    client_root: Path,
    profile_id: str,
    agent_id: str,
    target_instance_id: str,
    target_branch_id: str,
) -> dict[str, str]:
    """Resolve retry identity from an explicit local shadow branch binding."""
    profile = LocalProfileStore(client_root).load(profile_id)
    branch_ref = (
        f"graph-branch:{target_instance_id}:{target_branch_id}"
    )
    records = [
        item for item in profile["research_records"]
        if item["agent_id"] == agent_id
        and binding_for(item, branch_ref) is not None
    ]
    if len(records) != 1:
        raise click.ClickException(
            "continuation report retry requires one local target record"
        )
    target = records[0]
    binding = binding_for(target, branch_ref)
    if binding is None or binding["kind"] != "shadow_continuation":
        raise click.ClickException(
            "continuation report retry only accepts a shadow continuation"
        )
    source_ref = str(binding.get("source_branch_ref") or "")
    parts = source_ref.split(":")
    provenance = target.get("provenance") or {}
    source_work_package_id = str(
        provenance.get("source_work_package_id")
        or target["record_id"]
    )
    if (
        len(parts) != 3
        or parts[0] != "graph-branch"
        or not parts[1]
        or not parts[2]
        or not source_work_package_id
    ):
        raise click.ClickException(
            "shadow continuation source identity is incomplete"
        )
    return {
        "target_work_package_id": str(target["record_id"]),
        "source_work_package_id": source_work_package_id,
        "source_instance_id": parts[1],
        "source_branch_id": parts[2],
    }
