"""Freeze explicit Profile factor identities to immutable Git references."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.core.errors import friendly_errors
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.references.workspace_factor_reference import (
    freeze_factor_reference,
)


def register_factor_reference_commands(group: click.Group) -> None:
    group.add_command(freeze_factor)


@click.command("reference")
@click.argument("profile_id")
@click.option(
    "--source-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--identity", required=True)
@click.option(
    "--object-kind",
    type=click.Choice(["factor", "factor-family"]),
    required=True,
)
@click.option("--revision", default="HEAD", show_default=True)
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def freeze_factor(
    profile_id: str,
    source_file: Path,
    identity: str,
    object_kind: str,
    revision: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Return the exact target_ref for one committed Profile factor object."""
    root = load_profile_root(release_profile)
    profile = LocalProfileStore(root).load(profile_id)
    binding = profile.get("factor_workspace_binding") or {}
    worktree = str(binding.get("worktree_path") or "")
    if not worktree:
        raise ValueError("Profile has no registered factor worktree")
    value = freeze_factor_reference(
        object_kind=object_kind,
        scope=f"profile-{profile_id}",
        repository=Path(worktree),
        source_file=source_file,
        identity=identity,
        revision=revision,
    )
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        click.echo(value["target_ref"])
