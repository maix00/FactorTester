"""Explicit source-checkout policies used by client release commands."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


_REVISION = re.compile(r"^[0-9a-f]{40}$")


@contextmanager
def clean_worktree(repo: Path, revision: str) -> Iterator[Path]:
    """Materialize one explicitly requested commit in a temporary worktree.

    Release commands never call this implicitly. The caller must pass the
    commit through the public ``--from-clean-commit`` option.
    """
    if not _REVISION.fullmatch(revision):
        raise ValueError("clean commit must be a full lowercase Git SHA")
    resolved = subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
        cwd=repo,
        text=True,
    ).strip()
    if resolved != revision:
        raise ValueError("clean commit must resolve to the requested Git SHA")
    parent = Path(tempfile.mkdtemp(prefix="factortester-release-"))
    checkout = parent / "source"
    try:
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(checkout), revision],
            cwd=repo,
            check=True,
        )
        yield checkout
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(checkout)],
            cwd=repo,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        shutil.rmtree(parent, ignore_errors=True)
