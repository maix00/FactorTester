"""Locked, atomic publication of derived local research reports."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ..generation import publish_generation
from ..generation import work_package_lock
from ..git import commit_work_package
from ..journal import (
    assemble_snapshot,
    fragment_payload,
    journal_payload,
    load_fragments,
    logical_lineage,
    merge_fragment,
)
from ..markdown import MarkdownReportTarget
from ..schema import canonical_report_snapshot
from .aggregate import render_work_package_report
from . import index as report_index
from .index import ReportTarget


def render_branch_report(
    snapshot: dict[str, Any],
    *,
    workspace_root: Path,
    target: ReportTarget | None = None,
    journal_fragment: dict[str, Any] | None = None,
    journal_replaced_branch_id: str | None = None,
) -> dict[str, Any]:
    """Update one branch and its Work Package generation under one lock."""
    canonical = canonical_report_snapshot(snapshot)
    renderer = target or MarkdownReportTarget()
    package_root = (
        Path(workspace_root) / "research" / canonical["work_package_id"]
    )
    branch_path = (
        package_root / "branches" / canonical["branch_id"]
        / f"REPORT{renderer.extension}"
    )
    aggregate_path = package_root / "REPORT.md"
    index_path = package_root / "INDEX.json"
    assets_path = package_root / "assets"
    refs = report_index.artifact_refs(canonical, renderer.extension)

    with work_package_lock(package_root):
        fragment_targets = []
        physical_journal_path = branch_path.parent / "JOURNAL.json"
        logical_journal_path = branch_path.parent / "LOGICAL_JOURNAL.json"
        if journal_fragment is not None:
            target_sections_path = branch_path.parent / "sections"
            existing_fragments = load_fragments(target_sections_path)
            fragments, fragment_changed = merge_fragment(
                existing_fragments, journal_fragment,
            )
            all_fragments = _work_package_fragments(
                package_root,
                current_branch_id=canonical["branch_id"],
                current_fragments=fragments,
            )
            logical_fragments = logical_lineage(
                all_fragments,
                checkpoint_ref=journal_fragment["checkpoint_ref"],
            )
            rendered_snapshot = canonical_report_snapshot(
                assemble_snapshot(canonical, logical_fragments)
            )
            fragment_path = (
                branch_path.parent / "sections"
                / f"{journal_fragment['section_hash']}.json"
            )
            if fragment_changed:
                fragment_targets.append((
                    "journal_fragment", fragment_path,
                    fragment_payload(journal_fragment),
                ))
            physical_journal_bytes = journal_payload(
                work_package_id=canonical["work_package_id"],
                journal_kind="physical_branch",
                fragments=fragments,
            )
            logical_journal_bytes = journal_payload(
                work_package_id=canonical["work_package_id"],
                journal_kind="work_package",
                fragments=logical_fragments,
            )
        else:
            rendered_snapshot = canonical
            physical_journal_bytes = None
            logical_journal_bytes = None
        branch_payload = renderer.render(rendered_snapshot)
        content_hash = hashlib.sha256(branch_payload).hexdigest()
        existing_index = report_index.load_index(index_path, canonical)
        branch_section_prefix = f"report-section:{canonical['branch_id']}:"
        index = report_index.merge_index(
            existing_index,
            rendered_snapshot,
            renderer,
            content_hash,
            refs,
            replaced_branch_id=journal_replaced_branch_id,
            project_sections=(
                journal_fragment is None or fragment_changed
                or _index_requires_reprojection(
                    existing_index,
                    rendered_snapshot,
                    branch_section_prefix=branch_section_prefix,
                )
            ),
        )
        index_payload = report_index.encode_index(index)
        aggregate_payload = render_work_package_report(index)
        assets_path.mkdir(parents=True, exist_ok=True)
        targets = [
            ("branch", branch_path, branch_payload),
            ("work_package_report", aggregate_path, aggregate_payload),
            ("index", index_path, index_payload),
        ]
        if physical_journal_bytes is not None:
            targets.extend([
                ("physical_journal", physical_journal_path,
                 physical_journal_bytes),
                ("logical_journal", logical_journal_path,
                 logical_journal_bytes),
            ])
        targets.extend(fragment_targets)
        changed = publish_generation(targets)
        git = commit_work_package(
            package_root,
            message="Update research report checkpoint",
        )

    descriptor = _local_artifact_descriptor(
        refs=refs,
        branch_path=branch_path,
        index_path=index_path,
        content_hash=content_hash,
        branch_id=canonical["branch_id"],
        index=index,
        journal_path=(
            logical_journal_path if journal_fragment is not None else None
        ),
        journal_hash=(
            hashlib.sha256(logical_journal_bytes).hexdigest()
            if logical_journal_bytes is not None else None
        ),
    )
    return {
        "path": branch_path,
        "changed": any(changed.values()),
        "content_hash": content_hash,
        "source_hash": canonical["source_hash"],
        "branch_changed": changed["branch"],
        "index_changed": changed["index"],
        "work_package_report_changed": changed["work_package_report"],
        "index_path": index_path,
        "work_package_report_path": aggregate_path,
        "assets_path": assets_path,
        "artifact_refs": refs,
        "local_artifact_descriptor": descriptor,
        "journal_path": (
            logical_journal_path if journal_fragment is not None else None
        ),
        "journal_fragment_changed": (
            fragment_changed if journal_fragment is not None else False
        ),
        "git": git,
    }


def _index_requires_reprojection(
    index: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    branch_section_prefix: str,
) -> bool:
    """Detect a stale derived index without trusting the current branch alone."""
    if index["omitted_section_count"] != 0:
        return False
    indexed = {item["section_ref"] for item in index["sections"]}
    expected = {
        (
            f"report-section:"
            f"{section['branch_ref'].split(':')[-1]}:"
            f"{section['section_id']}"
        )
        for section in snapshot["sections"]
    }
    return (
        not any(
            item.startswith(branch_section_prefix)
            for item in indexed
        )
        or not expected.issubset(indexed)
    )


def stage_branch_fragment(
    fragment: dict[str, Any], *, workspace_root: Path, work_package_id: str,
) -> dict[str, Any]:
    """Persist one immutable fragment without publishing a report head."""
    branch_ref = str(fragment.get("branch_ref") or "")
    branch_parts = branch_ref.split(":")
    if len(branch_parts) != 3 or branch_parts[0] != "graph-branch":
        raise ValueError("research journal branch identity is invalid")
    branch_id = branch_parts[2]
    package_root = Path(workspace_root) / "research" / work_package_id
    sections_root = package_root / "branches" / branch_id / "sections"
    with work_package_lock(package_root):
        existing = load_fragments(sections_root)
        merged, changed = merge_fragment(existing, fragment)
        all_fragments = _work_package_fragments(
            package_root,
            current_branch_id=branch_id,
            current_fragments=merged,
        )
        logical_lineage(
            all_fragments,
            checkpoint_ref=fragment["checkpoint_ref"],
        )
        fragment_path = sections_root / f"{fragment['section_hash']}.json"
        writes = publish_generation([
            ("journal_fragment", fragment_path, fragment_payload(fragment)),
        ]) if changed else {"journal_fragment": False}
        git = commit_work_package(
            package_root,
            message="Stage research report checkpoint",
        )
    return {
        "changed": bool(writes["journal_fragment"]),
        "fragment_path": fragment_path,
        "git": git,
    }


def _work_package_fragments(
    package_root: Path, *, current_branch_id: str,
    current_fragments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result = list(current_fragments)
    branches_root = package_root / "branches"
    if not branches_root.exists():
        return result
    for branch_root in sorted(branches_root.iterdir()):
        if not branch_root.is_dir() or branch_root.name == current_branch_id:
            continue
        result.extend(load_fragments(branch_root / "sections"))
    return result


def _local_artifact_descriptor(
    *,
    refs: dict[str, str],
    branch_path: Path,
    index_path: Path,
    content_hash: str,
    branch_id: str,
    index: dict[str, Any],
    journal_path: Path | None,
    journal_hash: str | None,
) -> dict[str, Any]:
    descriptor = {
        "artifact_ref": refs["branch_report"],
        "format": "markdown",
        "status": "ready",
        "content_hash": content_hash,
        "local_ref": branch_path.resolve().as_uri(),
        "index_ref": index_path.resolve().as_uri(),
        "section_refs": [
            dict(link)
            for section in index["sections"]
            for link in section["links"]
        ],
    }
    if journal_path is not None and journal_hash is not None:
        descriptor.update({
            "journal_ref": journal_path.resolve().as_uri(),
            "journal_hash": journal_hash,
        })
    return descriptor
