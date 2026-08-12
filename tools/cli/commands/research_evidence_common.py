"""Shared native CLI helpers for Evidence commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_evidence_library import EvidenceLibrary


def read_object(path: Path, label: str = "JSON file") -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"invalid {label}: {path}") from exc
    if not isinstance(value, dict):
        raise click.ClickException(f"{label} must contain an object: {path}")
    return value


def emit(value: object, as_json: bool) -> None:
    click.echo(json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ))


def library_for_profile(
    *, release_profile: Path | None, profile_id: str,
) -> EvidenceLibrary:
    client_root = load_profile_root(release_profile)
    profile = LocalProfileStore(client_root).load(profile_id)
    workspace_root = Path(str(profile["workspace_root"])).resolve()
    if len(workspace_root.parents) < 2:
        raise click.ClickException("Profile workspace_root is invalid")
    user_root = workspace_root.parents[1]
    return EvidenceLibrary(user_root / "personal-workspace")


def profile_options(function):
    function = click.option(
        "--release-profile",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )(function)
    function = click.option("--profile-id", required=True)(function)
    return function
