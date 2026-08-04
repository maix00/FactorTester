"""CLI for the client-local product and factor catalog."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import click

import settings as Settings
from tools.cli.core.errors import friendly_errors
from tools.cli.release.profile import load_profile_root
from tools.cli.catalog import LocalCatalogStore
from tools.products.classifier_paths import parse_classifier_object_path


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
    database = legacy_db or Path(Settings.CACHE_DB_PATH)
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
        connection = sqlite3.connect(
            f"file:{database.expanduser().resolve()}?mode=ro", uri=True,
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
