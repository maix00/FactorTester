"""One-shot local research report migrations."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.core.errors import friendly_errors
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root


@click.command("migrate-work-packages")
@click.argument("profile_id")
@click.option("--apply", "apply_changes", is_flag=True)
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@friendly_errors
def migrate_work_packages(
    profile_id: str, apply_changes: bool, release_profile: Path | None,
) -> None:
    """Move retired report documents and Journals into branch trees once."""
    from tools.cli.release.research_reporting.authoring import (
        migrate_profile_work_packages,
    )

    receipt = migrate_profile_work_packages(
        client_root=load_profile_root(release_profile),
        profile_id=profile_id,
        apply=apply_changes,
    )
    click.echo(json.dumps(
        receipt, ensure_ascii=False, indent=2, sort_keys=True,
    ))
