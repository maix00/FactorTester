"""Atomic package application for result Action subject normalization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .journal import load_fragments
from .placeholder_apply import apply_migrated_package
from .result_subject_migration import migrate_result_action_subjects


def migrate_result_subject_package(
    *, package_root: Path, branch_id: str,
    apply: bool, client_root: Path | None = None,
    profile_id: str = "", agent_id: str = "",
) -> dict[str, Any]:
    """Dry-run or atomically migrate one local Work Package branch."""
    package_root = package_root.resolve()
    fragments = load_fragments(
        package_root / "branches" / branch_id / "sections"
    )
    migrated, receipt = migrate_result_action_subjects(fragments)
    receipt.update({
        "package_root": str(package_root),
        "branch_id": branch_id,
    })
    if not apply or not receipt["changed"]:
        receipt["mode"] = "dry_run" if not apply else "already_applied"
        return receipt
    product_group, current_node = _rebuild_metadata(
        package_root=package_root, fragments=fragments,
    )
    return apply_migrated_package(
        package_root=package_root, branch_id=branch_id,
        fragments=migrated, receipt=receipt,
        migration_slug="result-action-subject-v1",
        product_group=product_group, current_node=current_node,
        client_root=client_root, profile_id=profile_id, agent_id=agent_id,
        retain_superseded_inputs=False,
    )


def _rebuild_metadata(
    *, package_root: Path, fragments: list[dict[str, Any]],
) -> tuple[str, str]:
    """Read projection metadata already owned by the package and branch."""
    contract_path = package_root / "protocol" / "decision-contract.json"
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        product_group = str(contract["scope"]["product_group"]).strip()
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(
            "research package decision contract has no product group"
        ) from exc
    if not product_group:
        raise ValueError(
            "research package decision contract has no product group"
        )
    current_node = ""
    for fragment in reversed(fragments):
        for section in reversed(fragment.get("sections") or []):
            chapter_ref = str(section.get("chapter_ref") or "")
            if chapter_ref.startswith("node:"):
                current_node = chapter_ref.removeprefix("node:")
                break
        if current_node:
            break
    if not current_node:
        raise ValueError("research branch has no current node metadata")
    return product_group, current_node
