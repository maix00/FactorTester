"""One-time persistence of frozen obligation definitions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import click

from tools.cli.release.research_obligations import (
    ledger_path,
    load_ledger,
    write_ledger,
)
from tools.cli.release.research_reporting.git import commit_work_package


def register_definition_migration_command(
    obligation: click.Group,
    *,
    scope_resolver: Callable[..., tuple[Any, dict[str, Any]]],
) -> None:
    @obligation.command("migrate-definitions")
    @click.option("--instance-id", required=True)
    @click.option("--branch-id", required=True)
    @click.option("--profile-id", required=True)
    @click.option("--agent-id", required=True)
    @click.option(
        "--release-profile",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )
    @click.option("--apply", "apply_migration", is_flag=True)
    def migrate_definitions(
        instance_id: str,
        branch_id: str,
        profile_id: str,
        agent_id: str,
        release_profile: Path | None,
        apply_migration: bool,
    ) -> None:
        """Freeze the earliest definitions into all ledger snapshots."""
        scope, _packet = scope_resolver(
            instance_id, branch_id, profile_id, agent_id, release_profile,
        )
        path = ledger_path(scope.package_root, branch_id)
        try:
            before = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise click.ClickException(
                f"无法读取义务账本: {path}"
            ) from exc
        migrated = load_ledger(scope.package_root, branch_id)
        changed = before != migrated
        result: dict[str, Any] = {
            "status": (
                "migrated" if changed and apply_migration
                else "preview" if changed else "unchanged"
            ),
            "changed": changed,
            "ledger_file": str(path),
            "generation": int(migrated["generation"]),
            "projection_hash": migrated["current_projection"][
                "projection_hash"
            ],
        }
        if changed and apply_migration:
            write_ledger(scope.package_root, branch_id, migrated)
            result["git"] = commit_work_package(
                scope.package_root,
                message="Freeze obligation definitions in ledger history",
            )
        click.echo(json.dumps(result, ensure_ascii=False))
