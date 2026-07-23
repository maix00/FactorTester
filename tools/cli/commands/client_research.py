"""Cross-platform Work Package research projections."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.publisher import (
    MAX_CARRIER_BYTES,
    MAX_NARRATIVE_BYTES,
    finalize_historical_research_backfill,
    publish_research_checkpoint,
    stage_historical_research_checkpoint,
)


def _echo_json(value: dict) -> None:
    click.echo(json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ))


@click.group("research")
def client_research() -> None:
    """Inspect Work Packages and their Hypothesis Branches."""


@client_research.group("checkpoint")
def checkpoint() -> None:
    """Materialize bounded Active Graph checkpoints locally."""


@checkpoint.group("backfill")
def checkpoint_backfill() -> None:
    """Register trusted historical conversations without moving Graph HEAD."""


def _read_narrative(narrative_file) -> dict:
    payload = narrative_file.read(MAX_NARRATIVE_BYTES + 1)
    if len(payload.encode("utf-8")) > MAX_NARRATIVE_BYTES:
        raise ValueError(
            f"local narrative exceeds {MAX_NARRATIVE_BYTES} bytes"
        )
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("local narrative is not valid JSON") from exc


@checkpoint_backfill.command("stage")
@click.argument("profile_id")
@click.option("--agent-id", required=True)
@click.option("--work-package-ref", required=True)
@click.option("--branch-id", required=True)
@click.option("--trace-id", required=True)
@click.option(
    "--narrative-file",
    required=True,
    type=click.File("r", encoding="utf-8"),
    help="简体中文 narrative v3 历史研究叙事 JSON。",
)
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def stage_backfill_checkpoint(
    profile_id: str,
    agent_id: str,
    work_package_ref: str,
    branch_id: str,
    trace_id: str,
    narrative_file,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Stage one immutable historical fragment from a trusted server Carrier."""
    carrier = client_from_config().get_profile_research_report_carrier(
        work_package_ref, branch_id, trace_id,
    )
    _echo_json(stage_historical_research_checkpoint(
        client_root=load_profile_root(release_profile),
        profile_id=profile_id,
        agent_id=agent_id,
        current_branch_id=branch_id,
        carrier=carrier,
        narrative=_read_narrative(narrative_file),
    ))


@checkpoint_backfill.command("finalize")
@click.argument("profile_id")
@click.option("--agent-id", required=True)
@click.option("--work-package-ref", required=True)
@click.option("--branch-id", required=True)
@click.option(
    "--narrative-file",
    required=True,
    type=click.File("r", encoding="utf-8"),
    help="简体中文 narrative v3 当前 HEAD 叙事 JSON。",
)
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def finalize_backfill_checkpoint(
    profile_id: str,
    agent_id: str,
    work_package_ref: str,
    branch_id: str,
    narrative_file,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Finalize the staged root-to-current-HEAD lineage exactly once."""
    branch = client_from_config().get_profile_research_branch(
        work_package_ref, branch_id,
    )
    carrier = branch.get("report_checkpoint")
    if not isinstance(carrier, dict):
        raise ValueError("current research HEAD has no report Carrier")
    if carrier.get("checkpoint_ref") != branch.get("latest_trace_ref"):
        raise ValueError("current report Carrier does not match branch HEAD")
    _echo_json(finalize_historical_research_backfill(
        client_root=load_profile_root(release_profile),
        profile_id=profile_id,
        agent_id=agent_id,
        carrier=carrier,
        narrative=_read_narrative(narrative_file),
    ))


@checkpoint.command("publish")
@click.argument("profile_id")
@click.option("--agent-id", required=True)
@click.option(
    "--checkpoint-file",
    required=True,
    type=click.File("r", encoding="utf-8"),
    help="Bounded checkpoint JSON file, or '-' for stdin.",
)
@click.option(
    "--narrative-file",
    required=True,
    type=click.File("r", encoding="utf-8"),
    help="简体中文研究叙事 JSON 文件。",
)
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def publish_checkpoint(
    profile_id: str,
    agent_id: str,
    checkpoint_file,
    narrative_file,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Publish one server-produced checkpoint without HTTP or database I/O."""
    payload = checkpoint_file.read(MAX_CARRIER_BYTES + 1)
    if len(payload.encode("utf-8")) > MAX_CARRIER_BYTES:
        raise ValueError(
            f"checkpoint carrier exceeds {MAX_CARRIER_BYTES} bytes"
        )
    try:
        carrier = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("checkpoint carrier is not valid JSON") from exc
    narrative = _read_narrative(narrative_file)
    result = publish_research_checkpoint(
        client_root=load_profile_root(release_profile),
        profile_id=profile_id,
        agent_id=agent_id,
        carrier=carrier,
        narrative=narrative,
    )
    _echo_json(result)


@client_research.command("list")
@click.option("--workspace-ref", required=True)
@click.option(
    "--lifecycle",
    type=click.Choice(["active", "archived", "deleted"]),
    default="active",
    show_default=True,
)
@click.option("--limit", default=20, show_default=True, type=int)
@click.option("--after", default="")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_research(
    workspace_ref: str,
    lifecycle: str,
    limit: int,
    after: str,
    as_json: bool,
) -> None:
    """List one Work Package per research, never one row per branch."""
    value = client_from_config().list_profile_research(
        workspace_ref=workspace_ref,
        lifecycle=lifecycle,
        limit=limit,
        after=after,
    )
    _echo_json(value)


@client_research.command("show")
@click.argument("work_package_ref")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def show_research(work_package_ref: str, as_json: bool) -> None:
    """Show one Work Package with compact Hypothesis Branch summaries."""
    _echo_json(
        client_from_config().get_profile_research(work_package_ref)
    )


@client_research.command("lifecycle")
@click.argument("work_package_ref")
@click.option(
    "--target",
    required=True,
    type=click.Choice(["active", "archived", "deleted"]),
)
@click.option("--expected-revision", required=True, type=click.IntRange(min=1))
@click.option("--reason", required=True)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def change_research_lifecycle(
    work_package_ref: str,
    target: str,
    expected_revision: int,
    reason: str,
    as_json: bool,
) -> None:
    """Archive, activate, soft-delete, or restore one Work Package."""
    _echo_json(
        client_from_config().transition_profile_research_lifecycle(
            work_package_ref,
            target=target,
            expected_revision=expected_revision,
            reason=reason,
        )
    )


@client_research.command("branch")
@click.argument("work_package_ref")
@click.argument("branch_id")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def show_branch(
    work_package_ref: str,
    branch_id: str,
    as_json: bool,
) -> None:
    """Show one Hypothesis Branch current-state projection."""
    _echo_json(client_from_config().get_profile_research_branch(
        work_package_ref,
        branch_id,
    ))


@client_research.command("timeline")
@click.argument("work_package_ref")
@click.argument("branch_id")
@click.option("--limit", default=50, show_default=True, type=int)
@click.option("--after", default="")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def show_timeline(
    work_package_ref: str,
    branch_id: str,
    limit: int,
    after: str,
    as_json: bool,
) -> None:
    """Page compact transition refs for one Hypothesis Branch."""
    _echo_json(
        client_from_config().list_profile_research_branch_timeline(
            work_package_ref,
            branch_id,
            limit=limit,
            after=after,
        )
    )
