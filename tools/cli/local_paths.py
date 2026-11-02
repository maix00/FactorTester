"""Choose one local state authority without moving or copying user data."""

from __future__ import annotations

import os
from pathlib import Path


def select_existing_root(canonical: Path, legacy: Path, *, label: str) -> Path:
    """Use existing data during migration; reject divergent duplicate roots."""
    canonical_exists = canonical.exists() or canonical.is_symlink()
    legacy_exists = legacy.exists() or legacy.is_symlink()
    for path, exists in ((canonical, canonical_exists), (legacy, legacy_exists)):
        if exists and not path.is_dir():
            raise RuntimeError(f"{label} directory is invalid or has a broken link: {path}")
    if canonical_exists and legacy_exists:
        try:
            if not os.path.samefile(canonical, legacy):
                raise RuntimeError(f"{label} directories conflict; review local state migration")
        except FileNotFoundError as exc:
            raise RuntimeError(f"{label} directory changed during selection") from exc
    if canonical_exists:
        return canonical
    return legacy if legacy_exists else canonical


def documents_root() -> Path:
    documents = Path.home() / "Documents"
    return select_existing_root(documents / "TradeResearch", documents / "FactorTester",
                                label="TradeResearch documents")
