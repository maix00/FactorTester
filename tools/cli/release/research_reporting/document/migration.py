"""One-shot migration from legacy Graph-bound journals to split files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .bindings import bindings_hash, new_bindings
from .legacy_projection import project_fragment
from .model import document_hash, new_document
from .store import load_bindings, load_document, save_bindings, save_document


def migrate_legacy_journal(
    legacy_root: Path,
    document_output: Path,
    bindings_output: Path,
) -> dict[str, Any]:
    """Convert every historical fragment exactly once.

    The old files are read only during this command. The resulting report file
    contains content and assets only; all Graph, evidence, Job and checkpoint
    relations are written to the separate bindings file. Existing outputs must
    already be the new pair; legacy outputs are rejected instead of read back.
    """
    if document_output.exists() or bindings_output.exists():
        if not document_output.exists() or not bindings_output.exists():
            raise ValueError("migration requires both content and bindings outputs")
        document = load_document(document_output)
        bindings = load_bindings(bindings_output, document)
        return _receipt(document, bindings, migrated=False)
    paths = _fragment_paths(legacy_root)
    document = new_document("migrated-research-report", "迁移后的研究报告")
    bindings = new_bindings(document)
    migrated = 0
    source_hashes: list[str] = []
    for path in paths:
        try:
            raw = path.read_bytes()
            fragment = json.loads(raw.decode("utf-8"))
            if not isinstance(fragment, dict):
                raise ValueError("fragment must be an object")
            document, bindings, count, _asset_count = project_fragment(
                document, bindings, fragment,
            )
            migrated += count
            source_hashes.append(hashlib.sha256(raw).hexdigest())
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            # A one-shot migration must be complete. Silently skipping a
            # malformed historical fragment would create a plausible but
            # incomplete report and make the loss impossible to discover.
            raise ValueError(f"cannot migrate legacy fragment: {path}") from exc
    bindings["migration"] = {
        "kind": "legacy_graph_journal_to_content_bindings_v1",
        "source_root": str(legacy_root),
        "source_files": len(paths),
        "source_hash": hashlib.sha256(
            "".join(sorted(source_hashes)).encode()
        ).hexdigest(),
        "migrated_sections": migrated,
        "migrated_assets": len(document["assets"]),
        "skipped_files": 0,
    }
    bindings["document_hash"] = document_hash(document)
    save_document(document_output, document)
    save_bindings(bindings_output, bindings, document)
    return _receipt(document, bindings, migrated=True)


def _receipt(
    document: dict[str, Any], bindings: dict[str, Any], *, migrated: bool,
) -> dict[str, Any]:
    migration = bindings.get("migration") or {}
    return {
        "document": document,
        "bindings": bindings,
        "document_hash": document_hash(document),
        "bindings_hash": bindings_hash(bindings),
        "migrated": migrated,
        "metadata": migration,
    }


def _fragment_paths(root: Path) -> list[Path]:
    patterns = (
        "research/*/branches/*/sections/*.json",
        "branches/*/sections/*.json",
    )
    return sorted({path for pattern in patterns for path in root.glob(pattern)})
