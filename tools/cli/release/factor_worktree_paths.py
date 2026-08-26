"""Path policy for portable Profile factor worktrees."""

from __future__ import annotations

from pathlib import Path


def is_adoptable_factor_worktree_target(
    target: Path,
    *,
    profile_root: Path,
) -> bool:
    """Return whether the portable empty placeholder may become a worktree."""
    if target != profile_root / "factor-worktree":
        return False
    try:
        return target.is_dir() and next(target.iterdir(), None) is None
    except OSError:
        return False
