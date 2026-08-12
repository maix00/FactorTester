"""Resolve the exact source checkout used to restart Manager."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess


_REVISION = re.compile(r"^[0-9a-f]{40}$")


def resolve_manager_source(
    source_root: Path,
    *,
    source_mode: str,
    source_revision: str = "",
) -> Path:
    """Return an immutable Manager source for ``worktree`` or ``git-commit``.

    A worktree mode uses exactly the files supplied by the caller.  A
    git-commit mode materializes the requested full SHA in a persistent,
    detached checkout and verifies it on every reuse.  Neither mode silently
    falls back to the other one.
    """
    source = source_root.expanduser().resolve()
    if not (source / "server/manager/app.py").is_file():
        raise ValueError("Manager source lacks its entrypoint")
    if source_mode == "worktree":
        return source
    if source_mode != "git-commit":
        raise ValueError("source mode must be worktree or git-commit")
    revision = str(source_revision or "").strip()
    if not _REVISION.fullmatch(revision):
        raise ValueError("git-commit source mode requires a full lowercase Git SHA")

    repository = _repository_root(source)
    resolved = subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
        cwd=repository,
        text=True,
    ).strip()
    if resolved != revision:
        raise ValueError("requested Manager commit does not resolve exactly")

    # Keep immutable Manager checkouts below the Git repository.  Runtime
    # modules deliberately walk past nested ``.workspace`` worktrees to find
    # the primary repository and its sibling ``.settings`` file.  Placing the
    # checkout below the data root leaves no primary repository above it and
    # makes an otherwise valid commit fail during import.
    checkout = repository / ".workspace" / "manager-sources" / revision
    entrypoint = checkout / "server/manager/app.py"
    if checkout.exists():
        if not entrypoint.is_file():
            raise RuntimeError(f"existing Manager source cache is invalid: {checkout}")
        observed = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=checkout, text=True,
        ).strip()
        if observed != revision:
            raise RuntimeError(
                f"Manager source cache points to {observed}, expected {revision}"
            )
        return checkout

    checkout.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(checkout), revision],
        cwd=repository,
        check=True,
    )
    if not entrypoint.is_file():
        raise RuntimeError("requested Git commit lacks the Manager entrypoint")
    return checkout


def _repository_root(source: Path) -> Path:
    common = subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=source,
        text=True,
    ).strip()
    common_path = Path(common).resolve()
    return common_path.parent if common_path.name == ".git" else common_path
