"""Read retired report documents only for one-shot tree migration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .legacy_document import (
    legacy_bindings_path,
    load_legacy_bindings,
    load_legacy_document,
)


def discover_document_sources(
    package_root: Path, *, primary_branch_id: str,
) -> list[dict[str, Any]]:
    """Return validated root/branch documents, grouped by target branch."""
    candidates = [(primary_branch_id, package_root / "REPORT.json")]
    candidates.extend((path.parent.parent.name, path) for path in sorted(
        (package_root / "branches").glob("*/authoring/DOCUMENT.json")
    ))
    grouped: dict[str, dict[str, Any]] = {}
    for branch_id, document_path in candidates:
        if not document_path.is_file():
            continue
        binding_path = _binding_path(document_path)
        document = load_legacy_document(document_path)
        source = {
            "branch_id": branch_id,
            "document_path": document_path,
            "bindings_path": binding_path,
            "document": document,
            "bindings": load_legacy_bindings(binding_path, document),
        }
        previous = grouped.get(branch_id)
        if previous is not None and not equivalent_source(previous, source):
            raise ValueError("multiple retired report sources disagree for one branch")
        grouped[branch_id] = source
    return [grouped[key] for key in sorted(grouped)]


def equivalent_source(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return _digest(left["document"]) == _digest(right["document"]) and _digest(
        left["bindings"]
    ) == _digest(right["bindings"])


def source_receipt(source: dict[str, Any]) -> dict[str, str]:
    return {
        "branch_id": str(source["branch_id"]),
        "document": str(source["document_path"]),
        "bindings": str(source["bindings_path"]),
        "document_hash": _digest(source["document"]),
        "bindings_hash": _digest(source["bindings"]),
    }


def retire_source(source: dict[str, Any]) -> None:
    for field in ("document_path", "bindings_path"):
        path = Path(source[field])
        path.unlink()
        path.with_suffix(path.suffix + ".lock").unlink(missing_ok=True)


def _binding_path(document_path: Path) -> Path:
    candidates = [
        document_path.with_name("BINDINGS.json"),
        legacy_bindings_path(document_path),
    ]
    present = [path for path in candidates if path.is_file()]
    if len(present) != 1:
        raise ValueError("retired report document requires exactly one bindings file")
    return present[0]


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
