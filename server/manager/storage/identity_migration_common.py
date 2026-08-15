"""Shared contracts and safety helpers for account-identity migration."""

from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Mapping
from pathlib import Path

from server.manager.domain.organization_scope import canonical_username


SQLITE_USER_REFERENCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("account_factor_param_configs", ("username",)),
    ("account_factor_param_scopes", ("username",)),
    ("account_factor_research_runs", ("username",)),
    ("account_factor_sets", ("username",)),
    ("account_product_groups", ("username",)),
    ("account_templates", ("username",)),
    ("direct_trial_plans", ("owner",)),
    ("factor_family_catalog", ("owner_username",)),
    ("factor_family_catalog_params", ("owner_username",)),
    ("factor_family_sources", ("owner_username",)),
    ("factor_source_roots", ("username",)),
    ("factor_source_workspace_settings", ("username",)),
    ("levels", ("manager_username",)),
    ("active_research_graphs", ("activated_by",)),
    ("research_graph_versions", ("created_by",)),
    ("research_graph_trace", ("actor",)),
    ("research_report_item_checkpoints", ("actor",)),
    ("research_configuration_snapshots", ("owner",)),
    ("research_configurations", ("owner",)),
    ("research_evidence_admissions", ("owner",)),
    ("research_evidence_catalog_state", ("owner",)),
    ("research_evidence_fragments", ("owner",)),
    ("research_evidence_lifecycle", ("owner",)),
    ("research_evidence_lifecycle_transitions", ("owner",)),
    ("research_evidence_object_tags", ("owner",)),
    ("research_evidence_objects", ("owner",)),
    ("research_evidence_sources", ("owner",)),
    ("research_evidence_tag_proposals", ("owner",)),
    ("research_evidence_tags", ("owner",)),
    ("research_fragment_evidence_objects", ("owner",)),
    ("research_graph_instances", ("owner",)),
    ("research_graph_objects", ("owner",)),
    ("research_human_gate_overrides", ("owner",)),
    ("research_jobs", ("owner",)),
    ("research_maintenance_cases", ("owner_user_id",)),
    ("research_runs", ("owner",)),
    ("research_work_packages", ("owner",)),
    ("research_workspaces", ("owner",)),
    ("user_job_pins", ("owner",)),
    ("user_storage_policies", ("owner",)),
)

SYSTEM_OWNER_VALUES = frozenset({"__public_jobs__", "__public_graph__"})

POSTGRES_USER_REFERENCES: tuple[tuple[str, str], ...] = (
    ("control_devices", "username"),
    ("control_device_authorizations", "username"),
    ("control_user_preferences", "principal"),
    ("control_profiles", "principal"),
    ("source_versions", "principal"),
    ("quota_policies", "principal"),
    ("quota_server_usage", "principal"),
    ("quota_reservations", "principal"),
    ("control_levels", "manager_username"),
)


def choose_canonical_username(
    accounts: list[Mapping[str, object]],
    organization_id: str,
    alias: str,
) -> str:
    """Choose a new 12-digit suffix without reusing any account username."""
    existing = {
        str(item.get("username") or "")
        for item in accounts
        if isinstance(item, Mapping)
    }
    for _attempt in range(64):
        suffix = secrets.randbelow(900_000_000_000) + 100_000_000_000
        candidate = canonical_username(organization_id, alias, suffix)
        if candidate not in existing:
            return candidate
    raise RuntimeError("could not allocate a canonical username")


def sqlite_integrity_check(path: str | Path) -> None:
    with sqlite3.connect(Path(path).expanduser().resolve()) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    if not result or str(result[0]).lower() != "ok":
        raise RuntimeError(f"SQLite integrity check failed: {result!r}")


def backup_sqlite(source: str | Path, destination: str | Path) -> None:
    """Create a SQLite-consistent backup before a mutation."""
    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source_path) as source_connection:
        with sqlite3.connect(destination_path) as destination_connection:
            source_connection.backup(destination_connection)
            destination_connection.commit()
    sqlite_integrity_check(destination_path)


def cursor_rows_as_dicts(cursor: object) -> list[dict[str, object]]:
    """Normalize psycopg tuple or mapping rows for migration planning."""
    description = getattr(cursor, "description", None) or ()
    columns: list[str] = []
    for column in description:
        name = getattr(column, "name", None)
        columns.append(str(name if name is not None else column[0]))
    rows = cursor.fetchall()
    result: list[dict[str, object]] = []
    for row in rows:
        if isinstance(row, Mapping):
            result.append(dict(row))
        else:
            result.append(dict(zip(columns, row, strict=False)))
    return result
