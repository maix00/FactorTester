"""Manage immutable factor-set objects in a Profile factor worktree."""

from __future__ import annotations

import json
from pathlib import Path
import shlex

import click

from tools.cli.core.errors import friendly_errors
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.references.factor_set_git import (
    create_factor_set_manifest,
    freeze_factor_set_reference,
)
from tools.cli.release.research_reporting.references.factor_git import (
    validate_factor_reference,
)


def register_factor_set_commands(group: click.Group) -> None:
    group.add_command(factor_set)


@click.group("factor-set")
def factor_set() -> None:
    """Create and freeze named sets of committed factor expressions."""


@factor_set.command("create")
@click.argument("profile_id")
@click.option("--set-id", required=True)
@click.option("--title-zh", required=True)
@click.option("--member-ref", multiple=True, required=True)
@click.option("--replace", is_flag=True)
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def create_factor_set(
    profile_id: str,
    set_id: str,
    title_zh: str,
    member_ref: tuple[str, ...],
    replace: bool,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Write a factor-set manifest; commit it before creating a reference."""
    root = load_profile_root(release_profile)
    repository, roots = _factor_context(root, profile_id)
    for target_ref in member_ref:
        validate_factor_reference(
            kind="factor", target_ref=target_ref, roots=roots,
        )
    value = create_factor_set_manifest(
        repository=repository,
        scope=f"profile-{profile_id}",
        set_id=set_id,
        title_zh=title_zh,
        member_refs=list(member_ref),
        replace=replace,
    )
    value["next_actions"] = [{
        "description_zh": "提交成员清单后冻结因子集合引用",
        "command": (
            "git -C " + shlex.quote(str(repository)) + " add -- "
            + shlex.quote(str(value["manifest_path"]))
        ),
    }, {
        "description_zh": "冻结已提交的因子集合版本",
        "command": (
            "factortester client profile factor-worktree factor-set reference "
            f"{profile_id} --set-id {set_id} --json"
        ),
    }]
    _echo(value, as_json)


@factor_set.command("reference")
@click.argument("profile_id")
@click.option("--set-id", required=True)
@click.option("--revision", default="HEAD", show_default=True)
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def reference_factor_set(
    profile_id: str,
    set_id: str,
    revision: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Return one exact, committed factor-set target_ref."""
    root = load_profile_root(release_profile)
    repository, roots = _factor_context(root, profile_id)
    value = freeze_factor_set_reference(
        repository=repository,
        scope=f"profile-{profile_id}",
        set_id=set_id,
        roots=roots,
        revision=revision,
    )
    _echo(value, as_json)


def _factor_context(
    root: Path, profile_id: str,
) -> tuple[Path, dict[str, Path]]:
    profile = LocalProfileStore(root).load(profile_id)
    binding = profile.get("factor_workspace_binding") or {}
    worktree = str(binding.get("worktree_path") or "")
    if not worktree:
        raise ValueError("Profile has no registered factor worktree")
    repository = Path(worktree).expanduser().resolve()
    roots = {f"profile-{profile_id}": repository}
    workspace_root = Path(str(profile.get("workspace_root") or ""))
    if len(workspace_root.parents) >= 2:
        roots["personal"] = (
            workspace_root.parents[1]
            / "personal-workspace" / "factor-library"
        )
    return repository, roots


def _echo(value: dict, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        click.echo(str(value.get("target_ref") or value.get("set_ref") or ""))
