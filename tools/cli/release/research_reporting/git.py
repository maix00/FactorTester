"""Git persistence for local research Work Packages."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any


def commit_work_package(package_root: Path, *, message: str) -> dict[str, Any]:
    """Initialize and commit the tracked Work Package projection."""
    package_root = Path(package_root).expanduser().resolve()
    package_root.mkdir(parents=True, exist_ok=True)
    initialized = not (package_root / ".git").exists()
    if initialized:
        _run_git(package_root, "init", "--quiet")
        _run_git(package_root, "config", "user.name", "FactorTester Research")
        _run_git(package_root, "config", "user.email", "research@localhost")
    tracked = [
        name for name in (
            "INDEX.json", "REPORT.md", "branches", "assets", "artifacts",
            "migrations", "proposals", "protocol",
        ) if (package_root / name).exists()
    ]
    if tracked:
        _run_git(package_root, "add", "--all", "--", *tracked)
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
        raise RuntimeError(f"Work Package git operation failed: {detail}") from exc


def _head(package_root: Path) -> str:
    return _run_git(package_root, "rev-parse", "HEAD").stdout.strip()
