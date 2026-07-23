"""Atomic package publication for the one-shot placeholder migration."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any
import zipfile

from .journal import (
    assemble_snapshot, fragment_payload, journal_payload, load_fragments,
    logical_lineage,
)
from ..local_profile import LocalProfileStore
from .markdown import MarkdownReportTarget
from .placeholder_migration import migrate_placeholders
from .schema import canonical_report_snapshot
from .writer import index as report_index
from .writer.aggregate import render_work_package_report


def migrate_package(
    *, package_root: Path, branch_id: str,
    replacements: list[dict[str, str]], product_group: str,
    current_node: str, apply: bool,
    client_root: Path | None = None, profile_id: str = "",
    agent_id: str = "",
) -> dict[str, Any]:
    """Plan or atomically replace one complete Work Package directory."""
    package_root = package_root.resolve()
    source_root = package_root / "branches" / branch_id / "sections"
    fragments = load_fragments(source_root)
    migrated, receipt = migrate_placeholders(fragments, replacements)
    receipt["package_root"] = str(package_root)
    receipt["branch_id"] = branch_id
    if not apply or not receipt["changed"]:
        receipt["mode"] = "dry_run" if not apply else "already_applied"
        return receipt
    receipt["mode"] = "applied"

    parent = package_root.parent
    stage = Path(tempfile.mkdtemp(
        prefix=f".{package_root.name}.placeholder-new-", dir=parent,
    ))
    backup = parent / f".{package_root.name}.placeholder-backup"
    if backup.exists():
        shutil.rmtree(stage)
        raise ValueError("placeholder migration backup already exists")
    try:
        shutil.copytree(package_root, stage / package_root.name)
        staged_package = stage / package_root.name
        _backup_inputs(
            source=package_root,
            target=staged_package / "migrations"
            / "superseded-report-placeholders-v1.backup.zip",
            branch_id=branch_id,
        )
        _publish_migrated_package(
            package_root=staged_package,
            branch_id=branch_id,
            fragments=migrated,
            product_group=product_group,
            current_node=current_node,
            receipt=receipt,
        )
        os.replace(package_root, backup)
        try:
            os.replace(staged_package, package_root)
            if client_root is not None:
                _update_profile_artifact(
                    client_root=client_root,
                    profile_id=profile_id,
                    agent_id=agent_id,
                    package_root=package_root,
                    branch_id=branch_id,
                )
        except OSError:
            os.replace(backup, package_root)
            raise
        except Exception:
            failed = stage / f"{package_root.name}.failed"
            os.replace(package_root, failed)
            os.replace(backup, package_root)
            raise
        shutil.rmtree(backup)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return receipt


def _update_profile_artifact(
    *, client_root: Path, profile_id: str, agent_id: str,
    package_root: Path, branch_id: str,
) -> None:
    from .writer.service import _local_artifact_descriptor

    store = LocalProfileStore(client_root)
    profile = store.load(profile_id)
    matches = [
        item for item in profile["research_records"]
        if item["agent_id"] == agent_id
        and item["graph_branch_ref"].endswith(f":{branch_id}")
    ]
    if len(matches) != 1:
        raise ValueError("migration profile record is not unique")
    index = json.loads((package_root / "INDEX.json").read_text())
    report = package_root / "branches" / branch_id / "REPORT.md"
    journal = (
        package_root / "branches" / branch_id / "LOGICAL_JOURNAL.json"
    )
    refs = report_index.artifact_refs({
        "work_package_id": index["work_package_id"],
        "branch_id": branch_id,
    }, ".md")
    descriptor = _local_artifact_descriptor(
        refs=refs,
        branch_path=report,
        index_path=package_root / "INDEX.json",
        content_hash=hashlib.sha256(report.read_bytes()).hexdigest(),
        branch_id=branch_id,
        index=index,
        journal_path=journal,
        journal_hash=hashlib.sha256(journal.read_bytes()).hexdigest(),
    )
    record = dict(matches[0])
    record["artifacts"] = [
        item for item in record["artifacts"]
        if item["artifact_ref"] != descriptor["artifact_ref"]
    ] + [descriptor]
    record["timeline_refs"] = descriptor["section_refs"]
    store.upsert_research_record(profile_id, record)


def _backup_inputs(*, source: Path, target: Path, branch_id: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    paths = [
        source / "INDEX.json",
        source / "REPORT.md",
        source / "branches" / branch_id / "JOURNAL.json",
        source / "branches" / branch_id / "LOGICAL_JOURNAL.json",
        source / "branches" / branch_id / "REPORT.md",
    ]
    paths.extend(sorted(
        (source / "branches" / branch_id / "sections").glob("*.json")
    ))
    with zipfile.ZipFile(
        target, "w", compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for path in paths:
            archive.write(path, path.relative_to(source))


def _publish_migrated_package(
    *, package_root: Path, branch_id: str,
    fragments: list[dict[str, Any]], product_group: str,
    current_node: str, receipt: dict[str, Any],
) -> None:
    branch_root = package_root / "branches" / branch_id
    sections_root = branch_root / "sections"
    shutil.rmtree(sections_root)
    sections_root.mkdir(parents=True)
    for fragment in fragments:
        (sections_root / f"{fragment['section_hash']}.json").write_bytes(
            fragment_payload(fragment)
        )
    all_fragments = list(fragments)
    for other in sorted((package_root / "branches").iterdir()):
        if other.is_dir() and other.name != branch_id:
            all_fragments.extend(load_fragments(other / "sections"))
    head = fragments[-1]["checkpoint_ref"]
    logical = logical_lineage(all_fragments, checkpoint_ref=head)

    index_path = package_root / "INDEX.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    branch = next(
        item for item in index["branches"] if item["branch_id"] == branch_id
    )
    methodology_hash = _authoritative_methodology_hash(package_root)
    base = {
        "schema_version": 1,
        "workspace_id": index["workspace_id"],
        "work_package_id": index["work_package_id"],
        "branch_id": branch_id,
        "title": branch["title"],
        "status": branch["status"],
        "product_group": product_group,
        "current_node": current_node,
        "graph_ref": fragments[-1]["graph_ref"],
        "methodology_hash": methodology_hash,
        "decision_contract_hash": branch["decision_contract_hash"],
        "trial_plan_hash": branch["trial_plan_hash"],
        "factor_family_versions": branch["factor_family_versions"],
        "evidence_refs": branch["evidence_refs"],
        "sections": [],
        "assets": [],
        "gaps": [],
    }
    snapshot = canonical_report_snapshot(assemble_snapshot(base, logical))
    renderer = MarkdownReportTarget()
    rendered = renderer.render(snapshot)
    old_report = branch_root.joinpath("REPORT.md").read_bytes()
    report_bytes = _preserve_report_header(old_report, rendered)
    refs = report_index.artifact_refs(snapshot, renderer.extension)
    rebuilt_index = report_index.merge_index(
        index, snapshot, renderer, hashlib.sha256(report_bytes).hexdigest(),
        refs,
    )
    rebuilt_branch = next(
        item for item in rebuilt_index["branches"]
        if item["branch_id"] == branch_id
    )
    stable_fields = set(branch) - {"content_hash"}
    for field in stable_fields:
        rebuilt_branch[field] = branch[field]
    changed_identity = sorted(
        field for field in stable_fields
        if rebuilt_branch[field] != branch[field]
    )
    if changed_identity:
        raise ValueError(
            f"report migration changed research identity: {changed_identity}"
        )
    expected = {
        (section["checkpoint_ref"], section["section_id"])
        for section in snapshot["sections"]
    }
    indexed = {
        (section["checkpoint_ref"], section["section_id"])
        for section in rebuilt_index["sections"]
    }
    if expected != indexed:
        missing = sorted(expected - indexed)[:3]
        extra = sorted(indexed - expected)[:3]
        raise ValueError(
            "rebuilt report index is not a strict journal join: "
            f"expected={len(expected)} indexed={len(indexed)} "
            f"missing={missing!r} extra={extra!r}"
        )
    branch_root.joinpath("JOURNAL.json").write_bytes(journal_payload(
        work_package_id=index["work_package_id"],
        journal_kind="physical_branch", fragments=fragments,
    ))
    branch_root.joinpath("LOGICAL_JOURNAL.json").write_bytes(journal_payload(
        work_package_id=index["work_package_id"],
        journal_kind="work_package", fragments=logical,
    ))
    branch_root.joinpath("REPORT.md").write_bytes(report_bytes)
    index_path.write_bytes(report_index.encode_index(rebuilt_index))
    package_root.joinpath("REPORT.md").write_bytes(
        render_work_package_report(rebuilt_index)
    )
    migrations = package_root / "migrations"
    migrations.mkdir(exist_ok=True)
    migrations.joinpath("superseded-report-placeholders-v1.receipt.json"
                        ).write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n", encoding="utf-8",
    )


def _authoritative_methodology_hash(package_root: Path) -> str:
    values: set[str] = set()
    for path in [
        package_root / "protocol" / "bootstrap-evidence.json",
        *sorted((package_root / "proposals").glob("*.json")),
    ]:
        if not path.is_file():
            continue
        _collect_field(json.loads(path.read_text()), "methodology_hash", values)
    if len(values) != 1:
        raise ValueError("authoritative methodology_hash is unavailable")
    return values.pop()


def _collect_field(value: Any, field: str, result: set[str]) -> None:
    if isinstance(value, dict):
        candidate = value.get(field)
        if isinstance(candidate, str) and candidate:
            result.add(candidate)
        for item in value.values():
            _collect_field(item, field, result)
    elif isinstance(value, list):
        for item in value:
            _collect_field(item, field, result)


def _preserve_report_header(before: bytes, rebuilt: bytes) -> bytes:
    marker = b"\n## "
    before_at = before.find(marker)
    rebuilt_at = rebuilt.find(marker)
    if before_at < 0 or rebuilt_at < 0:
        raise ValueError("research report header cannot be preserved")
    return before[:before_at] + rebuilt[rebuilt_at:]
