"""Git persistence for local research Report Workspaces."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any


def commit_report_workspace(package_root: Path, *, message: str) -> dict[str, Any]:
    """Initialize and commit the tracked Report Workspace projection."""
    package_root = Path(package_root).expanduser().resolve()
    package_root.mkdir(parents=True, exist_ok=True)
    initialized = not (package_root / ".git").exists()
    if initialized:
        _run_git(package_root, "init", "--quiet")
        _run_git(package_root, "config", "user.name", "FactorTester Research")
        _run_git(package_root, "config", "user.email", "research@localhost")
    _ensure_transient_ignore(package_root)
    # A Report Workspace is owned as one local Git repository.  Do not maintain a
    # fixed allow-list here: users and research tools are allowed to add
    # package-scoped material (for example ``grill/``) which must survive
    # migration and participate in the same audit history.  The atomic report
    # store only leaves ``*.lock`` / ``*.tmp`` transient files, which are
    # explicitly excluded from commits.
    _run_git(
        package_root,
        "add", "--all", "--", ".",
        ":(exclude)*.lock", ":(exclude)**/*.lock",
        ":(exclude)*.tmp", ":(exclude)**/*.tmp",
        ":(exclude)pending-submission.json",
        ":(exclude)**/pending-submission.json",
        ":(exclude)submission.sqlite",
        ":(exclude)**/submission.sqlite",
        ":(exclude)**/submission.sqlite-*",
        ":(exclude)advance-reconciliation.json",
        ":(exclude)**/advance-reconciliation.json",
    )
    _run_git(
        package_root,
        "rm", "--cached", "--quiet", "--force", "--ignore-unmatch", "--",
        "pending-submission.json", ":(glob)**/pending-submission.json",
        "submission.sqlite", ":(glob)**/submission.sqlite",
        ":(glob)**/submission.sqlite-*",
        "advance-reconciliation.json",
        ":(glob)**/advance-reconciliation.json",
    )
    staged = _run_git(
        package_root, "diff", "--cached", "--name-only"
    ).stdout
    if not staged.strip():
        return {
            "initialized": initialized,
            "committed": False,
            "commit": _head(package_root),
        }
    _run_git(package_root, "commit", "--quiet", "-m", message)
    return {
        "initialized": initialized,
        "committed": True,
        "commit": _head(package_root),
    }


def _run_git(package_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(package_root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise RuntimeError(f"Report Workspace git operation failed: {detail}") from exc


def _head(package_root: Path) -> str:
    return _run_git(package_root, "rev-parse", "HEAD").stdout.strip()


def _ensure_transient_ignore(package_root: Path) -> None:
    """Keep atomic writer locks out of every Report Workspace status and commit."""
    path = package_root / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    required = (
        "*.lock", "*.tmp", "pending-submission.json", "submission.sqlite",
        "submission.sqlite-*", "advance-reconciliation.json", "index.sqlite",
        "index.sqlite-*",
    )
    missing = [item for item in required if item not in existing.splitlines()]
    if not missing:
        return
    suffix = "" if not existing or existing.endswith("\n") else "\n"
    path.write_text(existing + suffix + "\n".join(missing) + "\n", encoding="utf-8")
