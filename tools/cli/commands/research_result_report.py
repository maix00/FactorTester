"""High-level publication commands for audited Action results."""

import json
from pathlib import Path

import click

from tools.cli.commands.research_graph_chapter_reconciliation import (
    reconcile_current_container,
)
from tools.cli.commands.research_graph_local_report import (
    resolve_local_graph_report,
)
from tools.cli.commands.research_graph_report_policy import report_container
from tools.cli.core.context import client_from_config
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.publisher import (
    publish_current_node_report_checkpoint,
)


def register_research_result_report_commands(group) -> None:
    group.command("result-report")(_result_report)
    group.command("result-audit-backfill")(_audit_backfill)


@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--action-id", required=True)
@click.option("--work-package-id", required=True)
@click.option("--profile-id", required=True)
@click.option("--agent-id", required=True)
@click.option(
    "--release-profile", required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def _result_report(
    instance_id, branch_id, action_id, work_package_id,
    profile_id, agent_id, release_profile,
) -> None:
    root = load_profile_root(release_profile)
    LocalProfileStore(root).load(profile_id)
    client = client_from_config()
    projection = client.get_result_report_projection(
        instance_id, branch_id, action_id=action_id,
    )
    branch = client.get_profile_research_branch(
        f"work-package:{work_package_id}", branch_id,
    )
    carrier = branch.get("report_checkpoint")
    node_id = str(projection.get("node_id") or "")
    if not isinstance(carrier, dict) or carrier.get("current_node") != node_id:
        raise click.ClickException("result report node is no longer current")
    try:
        packet = client.get_research_graph_node_info(
            instance_id, branch_id,
        )
        scope = resolve_local_graph_report(
            client_root=root,
            profile_id=profile_id,
            agent_id=agent_id,
            instance_id=instance_id,
            branch_id=branch_id,
        )
        parent = reconcile_current_container(
            scope, container=report_container(packet),
        )
        published = publish_current_node_report_checkpoint(
            client_root=root, profile_id=profile_id, agent_id=agent_id,
            carrier=carrier, projection=projection,
            report_parent_id=str(parent["component_id"]),
        )
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    receipt = client.append_current_report_checkpoint(
        instance_id, branch_id, node_id=node_id,
        report_submission=published["report_submission"],
        report_artifact_ref=published["report_artifact_ref"],
    )
    click.echo(_json({
        "action_id": action_id, "audit_status": projection.get("audit_status"),
        "checkpoint_ref": published["checkpoint_ref"], "receipt": receipt,
        "changed": published["changed"],
    }))


@click.argument("instance_id")
@click.argument("branch_id")
@click.option(
    "--audited-checkpoint-file", required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--audit-payload-file", required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def _audit_backfill(
    instance_id, branch_id, audited_checkpoint_file, audit_payload_file,
) -> None:
    checkpoint = _checkpoint(_read(audited_checkpoint_file))
    payload = _read(audit_payload_file)
    if set(payload) != {"proposal", "decision"}:
        raise click.ClickException(
            "audit payload must contain exactly proposal and decision"
        )
    click.echo(_json(client_from_config().backfill_result_audit(
        instance_id, branch_id, audited_checkpoint=checkpoint,
        proposal=payload["proposal"], decision=payload["decision"],
    )))


def _read(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise click.ClickException("audit backfill files must be JSON objects")
    return value


def _checkpoint(value):
    if "checkpoint" not in value:
        return value
    checkpoint = value.get("checkpoint")
    if not isinstance(checkpoint, dict):
        raise click.ClickException(
            "authoritative audit output checkpoint must be a JSON object"
        )
    return checkpoint


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
