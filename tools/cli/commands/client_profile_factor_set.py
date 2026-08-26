"""Manage immutable factor-set objects in a Profile factor worktree."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root
from tools.cli.release.profile_factor_set_queries import (
    list_local_factor_sets,
    list_profile_factor_sets,
    profile_factor_context,
    resolve_factor_set_descriptor,
    resolve_factor_set_members,
    resolve_factor_set_run_input,
)
from tools.cli.release.research_reporting.references.factor_set_workspace import (
    create_factor_set_manifest,
    freeze_factor_set_reference,
    read_factor_set_manifest,
    validate_factor_set_reference,
)
from tools.cli.identities.factor import require_frozen_factor


def register_factor_set_commands(group: click.Group) -> None:
    group.add_command(factor_set)


@click.group("factor-set")
def factor_set() -> None:
    """Create and synchronize named sets of frozen factors."""


@factor_set.command("create")
@click.argument("profile_id")
@click.option("--set-id", required=True)
@click.option("--title-zh", required=True)
@click.option("--description-zh", default="")
@click.option("--member-record", multiple=True)
@click.option(
    "--member-record-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--replace", is_flag=True)
@click.option("--expected-member-fingerprint", default="")
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
    description_zh: str,
    member_record: tuple[str, ...],
    member_record_file: Path | None,
    replace: bool,
    expected_member_fingerprint: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Write a formula-addressed factor-set manifest."""
    root = load_profile_root(release_profile)
    repository, _roots = _factor_context(root, profile_id)
    members = _member_records(member_record, member_record_file)
    value = create_factor_set_manifest(
        repository=repository,
        scope=f"profile-{profile_id}",
        set_id=set_id,
        title_zh=title_zh,
        description_zh=description_zh,
        members=members,
        replace=replace,
        expected_member_fingerprint=expected_member_fingerprint,
    )
    value["next_actions"] = _sync_actions(profile_id=profile_id, set_id=set_id)
    _echo(_compact_manifest_result(value), as_json)


@factor_set.command("update")
@click.argument("profile_id")
@click.option("--set-id", required=True)
@click.option("--expected-member-fingerprint", required=True)
@click.option("--title-zh", required=True)
@click.option("--description-zh", default="")
@click.option("--member-record", multiple=True)
@click.option(
    "--member-record-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def update_factor_set(
    profile_id: str,
    set_id: str,
    expected_member_fingerprint: str,
    title_zh: str,
    description_zh: str,
    member_record: tuple[str, ...],
    member_record_file: Path | None,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Replace a manifest only when its current member hash still matches."""
    root = load_profile_root(release_profile)
    repository, _roots = _factor_context(root, profile_id)
    members = _member_records(member_record, member_record_file)
    value = create_factor_set_manifest(
        repository=repository,
        scope=f"profile-{profile_id}",
        set_id=set_id,
        title_zh=title_zh,
        description_zh=description_zh,
        members=members,
        replace=True,
        expected_member_fingerprint=expected_member_fingerprint,
    )
    value["next_actions"] = _sync_actions(profile_id=profile_id, set_id=set_id)
    _echo(_compact_manifest_result(value), as_json)


@factor_set.command("list")
@click.argument("profile_id")
@click.option("--query", default="")
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_factor_sets(
    profile_id: str,
    query: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """List workspace manifests and their formula-addressed identities."""
    root = load_profile_root(release_profile)
    profile = LocalProfileStore(root).load(profile_id)
    _echo(list_profile_factor_sets(profile=profile, query=query), as_json)


@factor_set.command("profiles")
@click.option("--query", default="")
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def profile_factor_sets(
    query: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """List factor sets from every local Profile in one bounded read."""
    root = load_profile_root(release_profile)
    profiles = LocalProfileStore(root).list()
    _echo(list_local_factor_sets(profiles=profiles, query=query), as_json)


@factor_set.command("show")
@click.argument("profile_id")
@click.option("--set-id", required=True)
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def show_factor_set(
    profile_id: str,
    set_id: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Show one working manifest without expanding member metadata."""
    root = load_profile_root(release_profile)
    repository, roots = _factor_context(root, profile_id)
    scope = f"profile-{profile_id}"
    value = read_factor_set_manifest(
        repository=repository, scope=scope, set_id=set_id,
    )
    try:
        target_ref = freeze_factor_set_reference(
            repository=repository, scope=scope, set_id=set_id, roots=roots,
        )["target_ref"]
        status = "committed"
    except ValueError as error:
        target_ref = None
        status = "not_frozen"
        validation_error = str(error)
    else:
        validation_error = None
    result = _summary(value, target_ref=target_ref, status=status)
    if validation_error:
        result["validation_error"] = validation_error
    result["member_resolution"] = {
        "command": "members",
        "default_page_size": 50,
    }
    _echo(result, as_json)


@factor_set.command("diff")
@click.option("--from-target-ref", required=True)
@click.option("--to-target-ref", required=True)
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
def diff_factor_sets(
    from_target_ref: str,
    to_target_ref: str,
    offset: int,
    limit: int,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Compare two immutable versions of one factor-set."""
    root = load_profile_root(release_profile)
    _before_profile, before = _resolve_target(root, from_target_ref)
    _after_profile, after = _resolve_target(root, to_target_ref)
    if (before["owner_ref"], before["set_id"]) != (
        after["owner_ref"], after["set_id"],
    ):
        raise ValueError("factor-set diff requires the same owner and set id")
    before_members = set(before["member_refs"])
    after_members = set(after["member_refs"])
    changes = [
        {"change": "added", "target_ref": target_ref}
        for target_ref in sorted(after_members - before_members)
    ] + [
        {"change": "removed", "target_ref": target_ref}
        for target_ref in sorted(before_members - after_members)
    ]
    page = changes[offset:offset + limit]
    _echo({
        "set_ref": before["target_ref"],
        "from_target_ref": from_target_ref,
        "to_target_ref": to_target_ref,
        "change_count": len(changes),
        "unchanged_count": len(before_members & after_members),
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(page) < len(changes),
        "next_offset": offset + len(page),
        "changes": page,
    }, as_json)


@factor_set.command("reference")
@click.argument("profile_id")
@click.option("--set-id", required=True)
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def reference_factor_set(
    profile_id: str,
    set_id: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Return one exact formula-addressed factor-set target_ref."""
    root = load_profile_root(release_profile)
    repository, roots = _factor_context(root, profile_id)
    value = freeze_factor_set_reference(
        repository=repository,
        scope=f"profile-{profile_id}",
        set_id=set_id,
        roots=roots,
    )
    value["next_actions"] = [{
        "action": "search_evidence",
        "description_zh": "按冻结集合身份检索可复用证据",
        "argv": [
            "factortester", "research", "evidence", "search",
            "--factor-ref", value["target_ref"], "--json",
        ],
    }]
    result = _compact_frozen(value)
    result["next_actions"] = value["next_actions"]
    _echo(result, as_json)


@factor_set.command("sync")
@click.argument("profile_id")
@click.option("--set-id", required=True)
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def sync_factor_set(
    profile_id: str,
    set_id: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Explicitly register one frozen local factor-set on the current server."""
    root = load_profile_root(release_profile)
    repository, roots = _factor_context(root, profile_id)
    frozen = freeze_factor_set_reference(
        repository=repository,
        scope=f"profile-{profile_id}",
        set_id=set_id,
        roots=roots,
    )
    value = client_from_config().register_factor_set({
        "target_ref": frozen["target_ref"],
        "manifest": frozen["descriptor"],
    })
    _echo(value.get("factor_set") or value, as_json)


@factor_set.command("unsync")
@click.option("--target-ref", required=True)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def unsync_factor_set(target_ref: str, as_json: bool) -> None:
    """Remove a server registration without deleting the local manifest."""
    _echo(client_from_config().unregister_factor_set(target_ref), as_json)


@factor_set.command("registered")
@click.option("--query", default="")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def registered_factor_sets(query: str, as_json: bool) -> None:
    """List factor sets explicitly registered on the current server."""
    _echo(client_from_config().list_registered_factor_sets(query=query), as_json)


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
    root = load_profile_root(release_profile)
    profile, _value = _resolve_target(root, target_ref)
    _echo(resolve_factor_set_members(
        profile=profile,
        target_ref=target_ref,
        offset=offset,
        limit=limit,
    ), as_json)


@factor_set.command("descriptor")
@click.option("--target-ref", required=True)
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def factor_set_descriptor(
    target_ref: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Return the exact immutable descriptor required by Run submission."""
    root = load_profile_root(release_profile)
    profile, _value = _resolve_target(root, target_ref)
    _echo(resolve_factor_set_descriptor(
        profile=profile, target_ref=target_ref,
    ), as_json)


@factor_set.command("run-input")
@click.option("--target-ref", required=True)
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def factor_set_run_input(
    target_ref: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Return exact local sources and descriptor for a single Run."""
    root = load_profile_root(release_profile)
    profile, _value = _resolve_target(root, target_ref)
    _echo(resolve_factor_set_run_input(
        profile=profile, target_ref=target_ref,
    ), as_json)


def _factor_context(
    root: Path, profile_id: str,
) -> tuple[Path, dict[str, Path]]:
    profile = LocalProfileStore(root).load(profile_id)
    return profile_factor_context(profile)


def _echo(value: dict, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        if isinstance(value.get("items"), list):
            for item in value["items"]:
                click.echo(
                    f"{item['set_id']}\t{item['member_count']}\t"
                    f"{item['status']}\t{item['title_zh']}"
                )
            return
        click.echo(str(value.get("target_ref") or value.get("set_ref") or ""))


def _member_records(
    direct: tuple[str, ...], source_file: Path | None,
) -> list[dict]:
    values: list[object] = []
    for item in direct:
        try:
            values.append(json.loads(item))
        except json.JSONDecodeError as error:
            raise ValueError("member-record must contain valid JSON") from error
    if source_file is not None:
        try:
            loaded = json.loads(source_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError("member-record-file must contain valid JSON") from error
        if not isinstance(loaded, list):
            raise ValueError("member-record-file must contain a JSON object array")
        values.extend(loaded)
    if not values:
        raise ValueError(
            "at least one --member-record or --member-record-file is required"
        )
    return [require_frozen_factor(value) for value in values]


def _resolve_target(root: Path, target_ref: str) -> tuple[dict, dict]:
    matches: list[tuple[dict, dict]] = []
    for profile in LocalProfileStore(root).list():
        try:
            _repository, roots = profile_factor_context(profile)
            value = validate_factor_set_reference(
                kind="factor", target_ref=target_ref, roots=roots,
            )
        except (OSError, ValueError):
            continue
        matches.append((profile, value))
    if len(matches) != 1:
        raise ValueError("factor-set ref is unavailable or ambiguous")
    return matches[0]


def _summary(value: dict, *, target_ref: str | None, status: str) -> dict:
    return {
        "set_id": value["identity"]["set_id"],
        "set_ref": value["ref"],
        "target_ref": target_ref,
        "title_zh": value["alias"],
        "description_zh": str(value.get("description") or ""),
        "member_count": len(value["identity"]["members"]),
        "member_fingerprint": value["identity"]["member_fingerprint"],
        "status": status,
    }


def _compact_manifest_result(value: dict) -> dict:
    result = _summary(value, target_ref=value["ref"], status="frozen")
    result["manifest_path"] = value.get("manifest_path")
    if value.get("next_actions"):
        result["next_actions"] = value["next_actions"]
    result["member_resolution"] = {
        "command": "members",
        "available_after_freeze": True,
        "default_page_size": 50,
    }
    return result


def _compact_frozen(value: dict) -> dict:
    result = {
        key: item for key, item in value.items()
        if key not in {"member_refs", "related_references", "descriptor"}
    }
    result["member_resolution"] = {
        "command": "members",
        "default_page_size": 50,
    }
    return result


def _sync_actions(*, profile_id: str, set_id: str) -> list[dict]:
    return [{
        "action": "sync_factor_set",
        "description_zh": "将冻结因子集合登记到当前服务器",
        "argv": [
            "factortester", "client", "profile", "factor-worktree",
            "factor-set", "sync", profile_id,
            "--set-id", set_id, "--json",
        ],
    }]
