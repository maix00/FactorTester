"""Manage immutable factor-set objects in a Profile factor worktree."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.core.errors import friendly_errors
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.references.factor_set_git import (
    create_factor_set_manifest,
    freeze_factor_set_reference,
    validate_factor_set_reference,
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
        if not target_ref.startswith("factor:v1:"):
            raise ValueError(
                "factor-set members must be frozen concrete factor:v1 references"
            )
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
        "action": "stage_manifest",
        "description_zh": "暂存因子集合清单",
        "argv": [
            "git", "-C", str(repository), "add", "--",
            str(value["manifest_path"]),
        ],
    }, {
        "action": "commit_manifest",
        "description_zh": "提交因子集合清单",
        "argv": [
            "git", "-C", str(repository), "commit", "-m",
            f"research: freeze factor set {set_id}", "--",
            str(value["manifest_path"]),
        ],
    }, {
        "action": "freeze_reference",
        "description_zh": "冻结已提交的因子集合版本",
        "argv": [
            "factortester", "client", "profile", "factor-worktree",
            "factor-set", "reference", profile_id,
            "--set-id", set_id, "--json",
        ],
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
    value["next_actions"] = [{
        "action": "search_evidence",
        "description_zh": "按冻结集合身份检索可复用证据",
        "argv": [
            "factortester", "research-evidence", "search",
            "--factor-ref", value["target_ref"], "--json",
        ],
    }]
    _echo(value, as_json)


@factor_set.command("members")
@click.option("--target-ref", required=True)
@click.option("--offset", type=click.IntRange(min=0), default=0, show_default=True)
@click.option(
    "--limit", type=click.IntRange(min=1, max=100), default=50,
    show_default=True,
)
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def factor_set_members(
    target_ref: str,
    offset: int,
    limit: int,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Resolve one frozen factor-set manifest into a bounded member page."""
    parts = target_ref.split(":")
    if len(parts) != 7 or parts[:2] != ["factor-set", "v1"]:
        raise ValueError("factor-set target_ref format is invalid")
    scope = parts[2]
    if not scope.startswith("profile-"):
        raise ValueError("factor-set member resolution requires a Profile scope")
    profile_id = scope.removeprefix("profile-")
    root = load_profile_root(release_profile)
    _repository, roots = _factor_context(root, profile_id)
    value = freeze_value = validate_factor_set_reference(
        kind="factor", target_ref=target_ref, roots=roots,
    )
    related = list(freeze_value["related_references"])
    page = related[offset:offset + limit]
    result = {
        "target_ref": target_ref,
        "set_ref": value["set_ref"],
        "title_zh": value["title_zh"],
        "member_hash": value["member_hash"],
        "member_count": len(related),
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(page) < len(related),
        "next_offset": offset + len(page),
        "related_references": page,
    }
    _echo(result, as_json)


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
