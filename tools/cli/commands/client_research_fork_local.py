"""Local Work Package side of a server-created research fork."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from tools.cli.release.research_reporting.authoring.export import (
    export_branch_report,
)
from tools.cli.release.research_reporting.authoring.tree_fork import (
    fork_report_tree,
)
from tools.cli.release.research_reporting.git import commit_work_package
from tools.cli.release.research_reporting.package_layout import (
    safe_package_component,
)


def source_package_root(
    profile: dict[str, Any], research_ref: str,
) -> Path:
    matches = [
        record for record in profile["research_records"]
        if record["graph_branch_ref"] == research_ref
    ]
    if len(matches) != 1:
        raise click.ClickException(
            "fork requires exactly one local research record for its source"
        )
    package_ref = str(matches[0]["graph_instance_ref"] or "")
    if not package_ref.startswith("work-package:"):
        raise click.ClickException(
            "source research record has no valid Work Package reference"
        )
    try:
        package_id = safe_package_component(
            package_ref.removeprefix("work-package:"),
            field="source Work Package id",
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    package_root = (
        Path(profile["workspace_root"]).expanduser()
        / "research" / package_id
    )
    if not package_root.is_dir():
        raise click.ClickException(
            "source Work Package is not initialized locally"
        )
    return package_root


def inherit_local_report(
    package_root: Path, source_branch_id: str, target_branch_id: str,
) -> dict[str, str]:
    target_branch_id = safe_package_component(
        target_branch_id, field="target branch_id",
    )
    fork_report_tree(
        package_root=package_root,
        source_branch_id=source_branch_id,
        target_branch_id=target_branch_id,
        target_report_id=f"report-{package_root.name}-{target_branch_id}",
    )
    export_branch_report(
        package_root=package_root,
        work_package_id=package_root.name,
        branch_id=target_branch_id,
        commit=False,
    )
    git = commit_work_package(
        package_root, message="Fork research report tree",
    )
    return {
        "path": str(package_root / "branches" / target_branch_id),
        "status": "inherited",
        "source_branch_id": source_branch_id,
        "commit": git["commit"],
    }
