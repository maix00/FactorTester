"""Retry local publication for an already-completed Graph transition."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from tools.cli.client import FactorTesterClient
from tools.cli.core.context import client_from_config
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root

from .research_graph_chapter_reconciliation import (
    synchronize_transition_container,
)
from .research_graph_local_report import (
    LocalGraphReport,
    resolve_local_graph_report,
)
from .research_graph_navigation import _publish_transition_report
from .research_graph_report_policy import report_container


def publish_transition_report(**kwargs: Any) -> dict[str, Any]:
    """Named seam shared by live execution and the safe retry command."""
    return _publish_transition_report(**kwargs)


def retry_latest_transition_report(
    *,
    client: FactorTesterClient,
    client_root: Path,
    local_report: LocalGraphReport,
    narrative_file: Path | None,
) -> dict[str, Any]:
    """Publish the current server Carrier without invoking node advance."""
    branch = client.get_profile_research_branch(
        f"work-package:{local_report.record['record_id']}",
        local_report.branch_id,
    )
    carrier = branch.get("report_checkpoint")
    if not isinstance(carrier, dict):
        raise ValueError("current transition report Carrier is unavailable")
    packet = client.get_research_graph_node_info(
        local_report.instance_id,
        local_report.branch_id,
    )
    current_node = str((packet.get("node") or {}).get("node_id") or "")
    if (
        not current_node
        or str(carrier.get("current_node") or "") != current_node
    ):
        raise ValueError(
            "transition report Carrier does not match current node"
        )
    chapter_sync = synchronize_transition_container(
        local_report,
        container=report_container(packet),
    )
    return publish_transition_report(
        branch={"report_checkpoint": carrier},
        client_root=client_root,
        profile_id=local_report.profile_id,
        agent_id=local_report.agent_id,
        instance_id=local_report.instance_id,
        branch_id=local_report.branch_id,
        narrative_file=narrative_file,
        chapter_sync=chapter_sync,
    )


def register_transition_report_commands(parent: click.Group) -> None:
    """Register a local-only retry for the latest completed transition."""

    @parent.command("transition-report-retry")
    @click.argument("instance_id")
    @click.argument("branch_id")
    @click.option("--profile-id", required=True)
    @click.option("--agent-id", required=True)
    @click.option(
        "--narrative-file",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )
    @click.option(
        "--release-profile",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )
    def transition_report_retry(
        instance_id: str,
        branch_id: str,
        profile_id: str,
        agent_id: str,
        narrative_file: Path | None,
        release_profile: Path | None,
    ) -> None:
        """Retry only the local report for the latest completed transition."""
        client_root = load_profile_root(release_profile)
        local_report = resolve_local_graph_report(
            client_root=client_root,
            profile_id=profile_id,
            agent_id=agent_id,
            instance_id=instance_id,
            branch_id=branch_id,
        )
        LocalProfileStore(client_root).load(profile_id)
        client = client_from_config()
        try:
            result = retry_latest_transition_report(
                client=client,
                client_root=client_root,
                local_report=local_report,
                narrative_file=narrative_file,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(json.dumps(
            result, ensure_ascii=False, indent=2, sort_keys=True,
        ))
