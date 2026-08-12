"""Freeze and inspect immutable local Profile configuration revisions."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.core.errors import friendly_errors
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.references.profile_revisions import (
    ProfileRevisionStore,
)


def register_profile_revision_commands(profile_group: click.Group) -> None:
    profile_group.add_command(profile_revision)


@click.group("revision")
def profile_revision() -> None:
    """Manage immutable Profile configuration references."""


@profile_revision.command("freeze")
@click.argument("profile_id")
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def freeze_profile_revision(
    profile_id: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Freeze the current Profile configuration and return its exact target."""
    root = load_profile_root(release_profile)
    snapshot = ProfileRevisionStore(root).freeze(
        LocalProfileStore(root).load(profile_id),
    )
    _output(snapshot, as_json)


@profile_revision.command("show")
@click.argument("target_ref")
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def show_profile_revision(
    target_ref: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Verify and show one exact immutable Profile configuration."""
    value = ProfileRevisionStore(
        load_profile_root(release_profile),
    ).load(target_ref)
    _output(value, as_json)


def _output(value: dict, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return
    click.echo(str(value["target_ref"]))
