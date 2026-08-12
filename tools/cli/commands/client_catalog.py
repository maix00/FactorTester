"""CLI for the client-local product and factor catalog."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import click

from tools.cli.core.errors import friendly_errors
from tools.cli.core.context import client_from_config
from tools.cli.release.profile import load_profile_root
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.user_layout import default_user_factor_library
from tools.cli.catalog import (
    describe_local_factor_family,
    LocalCatalogStore,
    instantiate_local_factor,
    list_local_factor_families,
    list_local_factor_revisions,
    resolve_local_factor_reference,
)
from tools.cli.catalog.product_paths import parse_classifier_object_path
from tools.cli.core.sqlite import connect_sqlite
from tools.cli.local_sources import ClientSourceCatalog


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _root_option(function):
    return click.option(
        "--release-profile",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )(function)


@click.group("catalog")
def client_catalog() -> None:
    """Manage the client-local product, factor and binding catalog."""


@client_catalog.group("source")
def catalog_source() -> None:
    """Read client-owned data-source manifests."""


@catalog_source.command("request", hidden=True)
@click.option("--path", required=True)
@click.option("--method", default="GET", type=click.Choice(["GET", "POST"]))
@click.option("--body-json", default="")
@_root_option
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def request_source_catalog(
    path: str,
    method: str,
    body_json: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Serve one allowlisted request for the native embedded catalog."""
    body: dict[str, Any] | None = None
    if body_json:
        try:
            parsed = json.loads(body_json)
        except json.JSONDecodeError as error:
            raise ValueError("local catalog request body is invalid") from error
        if not isinstance(parsed, dict):
            raise ValueError("local catalog request body must be an object")
        body = parsed
    value = ClientSourceCatalog(
        load_profile_root(release_profile),
    ).request(path, method=method, body=body)
    click.echo(_json(value) if as_json else _human_status(value))


@client_catalog.command("init")
@_root_option
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def init_catalog(release_profile: Path | None, as_json: bool) -> None:
    """Create or inspect the local catalog database without importing data."""
    value = LocalCatalogStore(load_profile_root(release_profile)).initialize()
    click.echo(_json(value) if as_json else _human_status(value))


@client_catalog.command("status")
@_root_option
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def catalog_status(release_profile: Path | None, as_json: bool) -> None:
    """Show local catalog schema and row counts."""
    value = LocalCatalogStore(load_profile_root(release_profile)).initialize()
    click.echo(_json(value) if as_json else _human_status(value))


@client_catalog.group("owner")
def catalog_owner() -> None:
    """Inspect factor repositories registered to this client identity."""


@catalog_owner.command("list")
@_root_option
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_owners(release_profile: Path | None, as_json: bool) -> None:
    client_root = load_profile_root(release_profile)
    value = _factor_owners(client_root)
    click.echo(_json(value) if as_json else _human_rows(
        value, "owner_ref", "display_name",
    ))


@client_catalog.group("revision")
def catalog_revision() -> None:
    """Inspect exact Git revisions for one factor owner."""


@catalog_revision.command("list")
@click.option("--owner-ref", required=True)
@click.option("--limit", default=50, type=click.IntRange(1, 200))
@_root_option
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_revisions(
    owner_ref: str,
    limit: int,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    value = list_local_factor_revisions(
        client_root=load_profile_root(release_profile),
        owner_ref=owner_ref,
        limit=limit,
    )
    click.echo(_json(value) if as_json else _human_rows(
        value, "git_commit", "subject",
    ))


@client_catalog.group("family")
def catalog_family() -> None:
    """Inspect factor families at one owner Git revision."""


@catalog_family.command("list")
@click.option("--owner-ref", required=True)
@click.option("--git-commit", required=True)
@_root_option
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_families(
    owner_ref: str,
    git_commit: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    value = list_local_factor_families(
        client_root=load_profile_root(release_profile),
        owner_ref=owner_ref,
        revision=git_commit,
    )
    click.echo(_json(value) if as_json else _human_rows(
        value, "family", "relative_path",
    ))


@catalog_family.command("describe")
@click.option("--owner-ref", required=True)
@click.option("--git-commit", required=True)
@click.option("--family", required=True)
@_root_option
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def describe_family(
    owner_ref: str,
    git_commit: str,
    family: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    value = describe_local_factor_family(
        client_root=load_profile_root(release_profile),
        owner_ref=owner_ref,
        revision=git_commit,
        family=family,
    )
    click.echo(_json(value) if as_json else value["family_ref"])


@client_catalog.group("group")
def catalog_group() -> None:
    """Inspect product groups and their local subject bindings."""


@catalog_group.command("list")
@_root_option
@click.option("--owner-ref")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_groups(
    release_profile: Path | None,
    owner_ref: str | None,
    as_json: bool,
) -> None:
    value = LocalCatalogStore(load_profile_root(release_profile)).list_groups(owner_ref)
    click.echo(_json(value) if as_json else _human_rows(value, "group_ref", "name"))


@catalog_group.command("subjects")
@click.argument("group_ref")
@_root_option
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_group_subjects(
    group_ref: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    value = LocalCatalogStore(load_profile_root(release_profile)).list_group_subjects(group_ref)
    click.echo(_json(value) if as_json else _human_rows(value, "subject_kind", "subject_ref"))


@client_catalog.group("factor")
def catalog_factor() -> None:
    """Inspect locally registered concrete factors."""


@catalog_factor.command("list")
@_root_option
@click.option("--owner-ref")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_factors(
    release_profile: Path | None,
    owner_ref: str | None,
    as_json: bool,
) -> None:
    value = LocalCatalogStore(load_profile_root(release_profile)).list_factors(owner_ref)
    click.echo(_json(value) if as_json else _human_rows(value, "factor_ref", "factor_name"))


@catalog_factor.command("resolve")
@click.option(
    "--owner-ref",
    default="",
    help="Profile 或用户 owner；省略时使用当前登录用户。",
)
@click.option("--git-commit", default="", help="精确 Git commit；省略时使用 HEAD。")
@click.option("--alias", required=True, help="完整具体因子 alias。")
@_root_option
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def resolve_factor(
    owner_ref: str,
    git_commit: str,
    alias: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Resolve local settings to one immutable concrete factor reference."""
    client_root = load_profile_root(release_profile)
    selected_owner = owner_ref.strip() or _current_user_owner_ref(client_root)
    value = resolve_local_factor_reference(
        client_root=client_root,
        owner_ref=selected_owner,
        alias=alias,
        revision=git_commit.strip() or "HEAD",
    )
    click.echo(_json(value) if as_json else value["factor_ref"])


@catalog_factor.command("instantiate")
@click.option("--owner-ref", required=True)
@click.option("--git-commit", required=True)
@click.option("--family", required=True)
@click.option("--params-json", required=True)
@_root_option
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def instantiate_factor(
    owner_ref: str,
    git_commit: str,
    family: str,
    params_json: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    try:
        params = json.loads(params_json)
    except json.JSONDecodeError as error:
        raise ValueError("factor params JSON is invalid") from error
    if not isinstance(params, dict):
        raise ValueError("factor params JSON must be an object")
    value = instantiate_local_factor(
        client_root=load_profile_root(release_profile),
        owner_ref=owner_ref,
        revision=git_commit,
        family=family,
        params=params,
    )
    click.echo(_json(value) if as_json else value["factor_ref"])


@client_catalog.group("factor-set")
def catalog_factor_set() -> None:
    """Inspect locally registered immutable factor-set manifests."""


@catalog_factor_set.command("list")
@_root_option
@click.option("--owner-ref")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_factor_sets(
    release_profile: Path | None,
    owner_ref: str | None,
    as_json: bool,
) -> None:
    value = LocalCatalogStore(load_profile_root(release_profile)).list_factor_sets(owner_ref)
    click.echo(_json(value) if as_json else _human_rows(value, "set_ref", "title_zh"))


@client_catalog.group("migration")
def catalog_migration() -> None:
    """Read-only checks for the pre-existing account product groups."""


@catalog_migration.command("preflight")
@click.option("--username", required=True)
@click.option(
    "--legacy-db",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Legacy account SQLite file; defaults to the runtime account database.",
)
@_root_option
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def migration_preflight(
    username: str,
    legacy_db: Path | None,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Inspect old product-group rows without writing or deleting anything."""
    if legacy_db is None:
        raise click.UsageError(
            "--legacy-db is required for the read-only migration preflight"
        )
    database = legacy_db
    groups = _read_legacy_groups(database, username)
    result = {
        "schema_version": 1,
        "mode": "read_only",
        "legacy_database": str(database.expanduser().resolve()),
        "local_catalog_database": str(
            LocalCatalogStore(load_profile_root(release_profile)).database_path
        ),
        "username": username,
        "group_count": len(groups),
        "groups": [_inspect_group(group) for group in groups],
        "safe_to_migrate": bool(groups) and all(
            item["migration_status"] == "canonical_paths_only"
            for item in map(_inspect_group, groups)
        ),
        "next_actions": [
            "resolve_category_paths_against_a_catalog_revision",
            "freeze_product_membership_hashes",
            "import_factor_and_factor_set_revisions",
            "verify_counts_before_removing_legacy_bindings",
        ],
    }
    click.echo(_json(result) if as_json else _human_preflight(result))


def _read_legacy_groups(database: Path, username: str) -> list[dict[str, Any]]:
    if not database.is_file():
        return []
    try:
        connection = connect_sqlite(
            database.expanduser().resolve(), readonly=True, timeout=5.0,
        )
    except sqlite3.Error:
        return []
    connection.row_factory = sqlite3.Row
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='account_product_groups'"
        ).fetchone()
        if table is None:
            return []
        rows = connection.execute(
            """
            SELECT group_name, sort_index, payload_json, updated_at
            FROM account_product_groups
            WHERE username = ?
            ORDER BY sort_index, group_name
            """,
            (username,),
        ).fetchall()
    finally:
        connection.close()
    result = []
    for row in rows:
        try:
            value = json.loads(str(row["payload_json"] or "{}"))
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        value.setdefault("name", row["group_name"])
        result.append(value)
    return result


def _inspect_group(group: dict[str, Any]) -> dict[str, Any]:
    paths = group.get("paths")
    if not isinstance(paths, list):
        paths = []
    canonical = 0
    category = 0
    invalid = 0
    for raw_path in paths:
        path = str(raw_path or "").strip()
        if path.startswith("-"):
            path = path[1:].strip()
        try:
            parse_classifier_object_path(path)
        except ValueError:
            if path.startswith("Product/") and len(path.split("/")) >= 3:
                category += 1
            else:
                invalid += 1
        else:
            canonical += 1
    if invalid:
        status = "invalid_paths"
    elif category:
        status = "category_paths_need_snapshot"
    else:
        status = "canonical_paths_only"
    return {
        "name": str(group.get("name") or ""),
        "group_ref": str(group.get("id") or ""),
        "path_count": len(paths),
        "canonical_path_count": canonical,
        "category_path_count": category,
        "invalid_path_count": invalid,
        "factor_ref_count": len(group.get("factor_refs") or []),
        "factor_set_ref_count": len(group.get("factor_set_refs") or []),
        "migration_status": status,
    }


def _human_status(value: dict[str, Any]) -> str:
    return (
        f"database={value['database']} schema={value['schema_version']} "
        f"products={value['products']} groups={value['product_groups']} "
        f"factors={value['factors']} factor_sets={value['factor_sets']}"
    )


def _human_preflight(value: dict[str, Any]) -> str:
    return (
        f"read-only groups={value['group_count']} "
        f"safe_to_migrate={str(value['safe_to_migrate']).lower()}\n"
        + "\n".join(
            f"{item['name']}: {item['migration_status']} "
            f"paths={item['path_count']}"
            for item in value["groups"]
        )
    )


def _human_rows(rows: list[dict[str, Any]], identity: str, label: str) -> str:
    if not rows:
        return "<empty>"
    return "\n".join(
        f"{row.get(identity) or '-'}\t{row.get(label) or '-'}"
        for row in rows
    )


def _current_user_owner_ref(client_root: Path) -> str:
    principal = client_from_config().current_principal()
    identity = str(
        principal.get("principal_ref") or principal.get("username") or ""
    ).strip()
    if not identity:
        local = {
            str((profile.get("session_binding") or {}).get("principal_ref") or "").strip()
            for profile in LocalProfileStore(client_root).list()
        }
        local.discard("")
        if len(local) != 1:
            raise ValueError(
                "current principal is unavailable and the local Profile registry "
                "does not identify exactly one user"
            )
        identity = local.pop()
    if identity.startswith(("user:", "principal:")):
        return identity
    return f"user:{identity}"


def _factor_owners(client_root: Path) -> list[dict[str, Any]]:
    result = []
    try:
        personal_ref = _current_user_owner_ref(client_root)
    except ValueError:
        personal_ref = ""
    if personal_ref:
        principal = personal_ref.split(":", 1)[1]
        repository = default_user_factor_library(principal).resolve()
        if repository.is_dir():
            result.append({
                "owner_ref": personal_ref,
                "display_name": principal,
                "owner_kind": "user",
                "repository": str(repository),
            })
    for profile in LocalProfileStore(client_root).list():
        profile_id = str(profile.get("profile_id") or "").strip()
        binding = profile.get("factor_workspace_binding") or {}
        repository = Path(
            str(binding.get("worktree_path") or "")
        ).expanduser()
        if not profile_id or not repository.is_dir():
            continue
        result.append({
            "owner_ref": f"profile:{profile_id}",
            "display_name": str(
                profile.get("display_name") or profile_id
            ),
            "owner_kind": "profile",
            "repository": str(repository.resolve()),
        })
    result.sort(key=lambda item: (
        item["owner_kind"] != "user", item["display_name"], item["owner_ref"],
    ))
    return result
