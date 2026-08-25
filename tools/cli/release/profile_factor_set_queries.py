"""Read-only factor-set queries shared by CLI and client surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.cli.release.research_reporting.references.factor_set_workspace import (
    factor_set_manifest_path,
    freeze_factor_set_reference,
    read_factor_set_manifest,
    validate_factor_set_reference,
)

MAX_LOCAL_FACTOR_SET_PROFILES = 512
MAX_LOCAL_FACTOR_SET_ITEMS = 10_000


def profile_factor_context(
    profile: dict[str, Any],
) -> tuple[Path, dict[str, Path]]:
    """Resolve the registered factor repository without invoking another CLI."""
    profile_id = str(profile.get("profile_id") or "").strip()
    if not profile_id:
        raise ValueError("Profile id is required")
    binding = profile.get("factor_workspace_binding") or {}
    worktree = str(binding.get("worktree_path") or "").strip()
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


def list_profile_factor_sets(
    *,
    profile: dict[str, Any],
    query: str = "",
    limit: int | None = None,
) -> dict[str, Any]:
    """List formula-addressed manifests; Git state is optional provenance."""
    profile_id = str(profile.get("profile_id") or "").strip()
    repository, roots = profile_factor_context(profile)
    scope = f"profile-{profile_id}"
    directory = factor_set_manifest_path(repository, "placeholder").parent
    needle = query.strip().casefold()
    items: list[dict[str, Any]] = []
    items_truncated = False
    paths = sorted(directory.glob("*.json")) if directory.is_dir() else []
    for path in paths:
        value = read_factor_set_manifest(
            repository=repository, scope=scope, set_id=path.stem,
        )
        haystack = " ".join([
            value["identity"]["set_id"], value["alias"],
            str(value.get("description") or ""),
        ]).casefold()
        if needle and needle not in haystack:
            continue
        if limit is not None and len(items) >= limit:
            items_truncated = True
            break
        try:
            frozen = freeze_factor_set_reference(
                repository=repository,
                scope=scope,
                set_id=value["identity"]["set_id"],
                roots=roots,
            )
            target_ref = frozen["target_ref"]
            status = "frozen"
            validation_error = None
        except ValueError as error:
            target_ref = None
            status = "not_frozen"
            validation_error = str(error)
        item = factor_set_summary(
            value, target_ref=target_ref, status=status,
        )
        if validation_error:
            item["validation_error"] = validation_error
        items.append(item)
    return {
        "profile_id": profile_id,
        "count": len(items),
        "items_truncated": items_truncated,
        "items": items,
    }


def list_local_factor_sets(
    *, profiles: list[dict[str, Any]], query: str = "",
) -> dict[str, Any]:
    """Aggregate bounded local factor-set summaries across all Profiles."""
    selected = profiles[:MAX_LOCAL_FACTOR_SET_PROFILES]
    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    items_truncated = False
    profiles_scanned = 0
    for index, profile in enumerate(selected):
        remaining = MAX_LOCAL_FACTOR_SET_ITEMS - len(items)
        if remaining <= 0:
            items_truncated = index < len(selected)
            break
        profile_id = str(profile.get("profile_id") or "").strip()
        display_name = str(profile.get("display_name") or profile_id).strip()
        profiles_scanned += 1
        try:
            result = list_profile_factor_sets(
                profile=profile, query=query, limit=remaining,
            )
        except (OSError, ValueError) as error:
            errors.append({
                "profile_id": profile_id,
                "profile_display_name": display_name,
                "error": str(error),
            })
            continue
        for item in result["items"]:
            items.append({
                **item,
                "profile_id": profile_id,
                "profile_display_name": display_name,
                "visibility": "local",
            })
        if result["items_truncated"]:
            items_truncated = True
            break
    return {
        "schema_version": 2,
        "scope": "local",
        "profiles_scanned": profiles_scanned,
        "profiles_total": len(profiles),
        "profiles_truncated": len(profiles) > len(selected),
        "count": len(items),
        "items_truncated": items_truncated,
        "items": items,
        "errors": errors,
    }


def resolve_factor_set_members(
    *,
    profile: dict[str, Any],
    target_ref: str,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    """Resolve a bounded page from one immutable factor-set reference."""
    _repository, roots = profile_factor_context(profile)
    value = validate_factor_set_reference(
        kind="factor", target_ref=target_ref, roots=roots,
    )
    related = list(value["related_references"])
    page = related[offset:offset + limit]
    return {
        "target_ref": target_ref,
        "alias": value["alias"],
        "member_fingerprint": value["member_fingerprint"],
        "member_count": len(related),
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(page) < len(related),
        "next_offset": offset + len(page),
        "related_references": page,
    }


def resolve_factor_set_descriptor(
    *, profile: dict[str, Any], target_ref: str,
) -> dict[str, Any]:
    """Return the exact formula-addressed descriptor used by Run submission."""
    _repository, roots = profile_factor_context(profile)
    value = validate_factor_set_reference(
        kind="factor", target_ref=target_ref, roots=roots,
    )
    return {
        "target_ref": value["target_ref"],
        "manifest": value["descriptor"],
    }


def resolve_factor_set_run_input(
    *, profile: dict[str, Any], target_ref: str,
) -> dict[str, Any]:
    """Return one immutable descriptor; sources resolve by frozen factor ref."""
    _repository, roots = profile_factor_context(profile)
    value = validate_factor_set_reference(
        kind="factor", target_ref=target_ref, roots=roots,
    )
    return {
        "descriptor": {
            "target_ref": value["target_ref"],
            "manifest": value["descriptor"],
        },
        "transient_factor_sources": [],
    }


def factor_set_summary(
    value: dict[str, Any], *, target_ref: str | None, status: str,
) -> dict[str, Any]:
    return {
        "set_id": value["identity"]["set_id"],
        "set_ref": target_ref,
        "target_ref": target_ref,
        "title_zh": value["alias"],
        "description_zh": str(value.get("description") or ""),
        "member_count": len(value["identity"]["members"]),
        "member_fingerprint": value["identity"]["member_fingerprint"],
        "status": status,
    }
