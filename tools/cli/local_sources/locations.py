"""Stable device-local locations for client-owned data sources."""

from __future__ import annotations

from pathlib import Path
from tools.cli.local_paths import documents_root


def default_local_sources_root() -> Path:
    """Return the shared source-plugin root for this macOS user account."""
    return validate_local_sources_root(
        documents_root() / "sources"
    )


def validate_local_sources_root(root: Path) -> Path:
    """Reject broad roots before installing managed source templates."""
    resolved = root.expanduser().resolve()
    home = Path.home().resolve()
    forbidden = {
        Path("/").resolve(),
        home,
        (home / "Documents").resolve(),
        (home / "Documents" / "FactorTester").resolve(),
        (home / "Documents" / "TradeResearch").resolve(),
    }
    if resolved in forbidden or len(resolved.parts) < 4:
        raise ValueError(f"unsafe local source root: {resolved}")
    return resolved
