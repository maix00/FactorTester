"""Discovery and preflight checks for files retired by the one-shot migration."""

from __future__ import annotations

from pathlib import Path


def journals(package: Path) -> list[Path]:
    return sorted((package / "branches").glob("*/JOURNAL.json"))


def projection_branches(package: Path) -> list[str]:
    return sorted({
        path.parent.parent.name
        for path in (package / "branches").glob("*/sections/*.json")
    } | {
        path.parent.name
        for path in (package / "branches").glob("*/LOGICAL_JOURNAL.json")
    })


def retired_root_paths(package: Path) -> list[Path]:
    return [
        path for path in (package / "INDEX.json", package / "REPORT.md")
        if path.exists()
    ]


def verify_projection_ownership(
    journals: list[Path], projection_branch_ids: list[str],
) -> None:
    journal_branch_ids = {path.parent.name for path in journals}
    orphaned = sorted(set(projection_branch_ids) - journal_branch_ids)
    if orphaned:
        raise ValueError(
            "retired report projections have no matching JOURNAL source: "
            + ", ".join(orphaned)
        )
