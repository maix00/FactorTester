"""One-shot local research report migrations."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.core.errors import friendly_errors
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root


@click.command("migrate-result-subjects")
@click.argument("profile_id")
@click.option("--agent-id", required=True)
@click.option("--work-package-id", required=True)
@click.option("--branch-id", required=True)
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--apply", "apply_changes", is_flag=True)
@friendly_errors
def migrate_result_subjects(
    profile_id: str, agent_id: str, work_package_id: str,
    branch_id: str, release_profile: Path | None, apply_changes: bool,
) -> None:
    """Normalize duplicated Action prefixes in historical result reports."""
    from tools.cli.release.research_reporting.result_subject_apply import (
        migrate_result_subject_package,
    )

    client_root = load_profile_root(release_profile)
    profile = LocalProfileStore(client_root).load(profile_id)
    package = (
        Path(profile["workspace_root"]) / "research" / work_package_id
    )
    receipt = migrate_result_subject_package(
        package_root=package, branch_id=branch_id,
        apply=apply_changes, client_root=client_root,
        profile_id=profile_id, agent_id=agent_id,
    )
    click.echo(json.dumps(
        receipt, ensure_ascii=False, indent=2, sort_keys=True,
    ))
