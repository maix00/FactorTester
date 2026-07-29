"""CLI gate for an explicit legacy checkpoint-to-node migration."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.authoring.export import (
    export_branch_report,
)
from tools.cli.release.research_reporting.maintenance.history_chapters import (
    migrate_history_chapters,
)
from .research_report_common import output, scope_options
from .research_report_scope import (
    load_current_authoring,
    persist_descriptor,
    resolve_history_migration_scope,
)


@click.command("migrate-history-chapters")
@scope_options
@click.option(
    "--authority-file", required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--apply", "apply_changes", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def migrate_history_chapters_command(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, authority_file: Path,
    apply_changes: bool, as_json: bool,
) -> None:
    """Rename legacy checkpoint chapters from an explicit authority manifest."""
    try:
        mapping = _authority(authority_file, branch_id=branch_id)
        if not apply_changes:
            output({
                "mode": "plan", "branch_id": branch_id,
                "checkpoint_count": len(mapping),
            }, as_json)
            return
        scope = resolve_history_migration_scope(
            client_root=load_profile_root(release_profile),
            profile_id=profile_id, work_package_id=work_package_id,
            branch_id=branch_id,
        )
        migrated = migrate_history_chapters(
            package_root=scope.package_root, branch_id=branch_id,
            checkpoint_nodes=mapping,
        )
        rendered = export_branch_report(
            package_root=scope.package_root,
            work_package_id=work_package_id, branch_id=branch_id,
            message="Migrate report checkpoint chapters",
        )
        persist_descriptor(
            scope,
            load_current_authoring(scope)["descriptor"],
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    output({
        "mode": "applied", **migrated,
        "report_path": str(rendered["path"]), "git": rendered["git"],
    }, as_json)


def _authority(path: Path, *, branch_id: str) -> dict[str, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("history chapter authority file is invalid") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "branch_id", "checkpoints"}
        or value["schema_version"] != 1
        or value["branch_id"] != branch_id
        or not isinstance(value["checkpoints"], list)
    ):
        raise ValueError("history chapter authority schema is invalid")
    result: dict[str, str] = {}
    for item in value["checkpoints"]:
        if not isinstance(item, dict) or set(item) != {
            "checkpoint_ref", "node_id", "authority_ref",
        }:
            raise ValueError("history chapter authority entry is invalid")
        checkpoint = str(item["checkpoint_ref"])
        node_id = str(item["node_id"])
        authority = str(item["authority_ref"])
        if not checkpoint or not node_id or not authority:
            raise ValueError("history chapter authority entry is incomplete")
        if checkpoint in result and result[checkpoint] != node_id:
            raise ValueError("history checkpoint maps to multiple nodes")
        result[checkpoint] = node_id
    return result
