"""Local Work Package side of a server-created research fork."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from tools.cli.release.research_branch_bindings import (
    owns_branch,
    with_branch_binding,
)
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.research_reporting.authoring.export import (
    export_branch_report,
)
from tools.cli.release.research_reporting.authoring.tree_fork import (
    fork_report_tree,
)
from tools.cli.release.research_reporting.work_package_identity import (
    work_package_report_id,
)
from tools.cli.release.research_reporting.git import commit_work_package
from tools.cli.release.research_reporting.package_layout import (
    safe_package_component,
)
from tools.cli.release.research_obligations import (
    inherit_obligation_ledger,
)


def source_package_root(
    profile: dict[str, Any], research_ref: str,
) -> Path:
    matches = [
        record for record in profile["research_records"]
        if owns_branch(record, research_ref)
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


def bind_local_fork(
    *,
    client_root: Path,
    profile_id: str,
    source_ref: str,
    target_ref: str,
) -> None:
    store = LocalProfileStore(client_root)
    profile = store.load(profile_id)
    matches = [
        record for record in profile["research_records"]
        if owns_branch(record, source_ref)
    ]
    if len(matches) != 1:
        raise ValueError("fork source Work Package does not resolve locally")
    updated = with_branch_binding(
        matches[0],
        branch_ref=target_ref,
        kind="fork",
        source_branch_ref=source_ref,
    )
    store.upsert_research_record(profile_id, updated)


def inherit_local_report(
    package_root: Path,
    source_branch_id: str,
    target_branch_id: str,
    *,
    target_instance_id: str,
    target_packet: dict[str, Any],
) -> dict[str, Any]:
    target_branch_id = safe_package_component(
        target_branch_id, field="target branch_id",
    )
    fork_report_tree(
        package_root=package_root,
        source_branch_id=source_branch_id,
        target_branch_id=target_branch_id,
        target_report_id=work_package_report_id(package_root, package_root.name),
    )
    export_branch_report(
        package_root=package_root,
        work_package_id=package_root.name,
        branch_id=target_branch_id,
        commit=False,
    )
    ledger = inherit_obligation_ledger(
        source_package_root=package_root,
        target_package_root=package_root,
        source_branch_id=source_branch_id,
        target_branch_id=target_branch_id,
        target_instance_id=target_instance_id,
        target_packet=target_packet,
        inheritance_kind="branch_fork",
    )
    git = commit_work_package(
        package_root, message="Fork research report and obligation ledger",
    )
    return {
        "path": str(package_root / "branches" / target_branch_id),
        "status": "inherited",
        "source_branch_id": source_branch_id,
        "obligation_ledger_inherited": ledger["inherited"],
        "commit": git["commit"],
    }
