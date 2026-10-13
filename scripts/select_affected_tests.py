#!/usr/bin/env python3
"""Conservatively select pytest modules for a Git hook.

The mapping is deliberately coarse. A path not classified here runs the full
suite; this is preferable to silently omitting a test when ownership changes.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ZERO_SHA = "0" * 40
TEST_MODULES = {
    "analytics", "backtest", "calc", "catalog", "cli", "data", "factors",
    "group", "js", "migrations", "products", "release", "scripts", "server",
    "skills", "sources", "templates", "testers", "traderules",
}
# Cross-module consumers are included, even if a test does not directly import
# the changed package. Keep these groups broad until dependency coverage can
# justify a narrower selection.
IMPACT = {
    "server": ("server", "scripts", "release", "cli", "catalog", "backtest",
               "data", "factors", "group", "migrations", "products", "templates"),
    "cli": ("cli", "release", "scripts", "server", "catalog"),
    "factors": ("factors", "calc", "group", "backtest", "testers", "server",
                "catalog", "data", "migrations", "release", "scripts"),
    "testers": ("testers", "group", "backtest", "server", "release", "factors", "scripts"),
    "data": ("data", "sources", "products", "factors", "testers", "backtest",
             "calc", "catalog", "scripts", "server"),
    "products": ("products", "data", "sources", "testers", "backtest", "factors", "server"),
    "sources": ("sources", "data", "products", "testers", "backtest"),
    "analytics": ("analytics", "testers", "group", "server"),
    "traderules": ("traderules", "backtest", "testers"),
    "migrations": ("migrations", "server", "release", "data"),
    "templates": ("templates", "server", "release"),
    "apple": ("release", "cli"),
    "skills": ("skills",),
    "js": ("js", "server", "release"),
}
LEAF_TEST_MODULES = {"calc", "catalog", "group", "backtest", "scripts", "release"}
FULL_PATHS = {
    "AGENTS.md", "CONTEXT.md", "conftest.py", "environment.yml", "pytest.ini",
    "pyproject.toml", "setup.cfg", "requirements.txt", "scripts/test.sh",
    "scripts/select_affected_tests.py", ".githooks/pre-commit", ".githooks/pre-push",
}


def _git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def paths_from_name_status(data: bytes) -> set[str]:
    """Parse Git's NUL-delimited name-status format, including both rename ends."""
    tokens = data.decode("utf-8", "surrogateescape").split("\0")
    paths: set[str] = set()
    pos = 0
    while pos < len(tokens) and tokens[pos]:
        status = tokens[pos]
        pos += 1
        count = 2 if status[0] in "RC" else 1
        if pos + count > len(tokens) - 1:
            raise ValueError("incomplete Git name-status output")
        paths.update(tokens[pos : pos + count])
        pos += count
    return paths


def staged_paths() -> set[str]:
    return paths_from_name_status(
        _git("diff", "--cached", "--name-status", "-z", "--find-renames")
    )


def pushed_paths(ref_lines: str) -> set[str] | None:
    """Return None when a push cannot be bounded safely (then run all tests)."""
    if not ref_lines.strip():
        return None
    paths: set[str] = set()
    for line in ref_lines.splitlines():
        fields = line.split()
        if len(fields) != 4:
            return None
        _, local_sha, _, remote_sha = fields
        if local_sha == ZERO_SHA:  # Deleting a remote ref changes no code.
            continue
        if remote_sha == ZERO_SHA:
            try:
                remote_sha = _git("merge-base", "origin/feat", local_sha).decode().strip()
            except subprocess.CalledProcessError:
                return None
        try:
            diff = _git("diff", "--name-status", "-z", "--find-renames", remote_sha, local_sha)
        except subprocess.CalledProcessError:
            return None
        paths.update(paths_from_name_status(diff))
    return paths


def select(paths: set[str] | None) -> tuple[str, list[str]]:
    if paths is None:
        return "FULL", []
    modules: set[str] = set()
    for path in paths:
        parts = Path(path).parts
        if not parts:
            return "FULL", []
        if path in FULL_PATHS or parts[-1] == "AGENTS.md" or parts[0] in {".github", "deploy", "environments", "third_party"}:
            return "FULL", []
        if parts[0] == "docs" or (path.endswith((".md", ".rst")) and parts[0] != "skills"):
            continue
        if parts[0] == "tests":
            if len(parts) < 3 or parts[1] not in TEST_MODULES:
                return "FULL", []
            if parts[-1] in {"conftest.py", "__init__.py"}:
                modules.add(f"tests/{parts[1]}")
            elif parts[-1].startswith("test_") and path.endswith(".py"):
                modules.add(path if (ROOT / path).exists() else f"tests/{parts[1]}")
            else:
                modules.add(f"tests/{parts[1]}")
            continue
        if parts[0] == "server" and len(parts) > 1:
            modules.update(f"tests/{name}" for name in IMPACT["server"])
            modules.add("tests/test_sse_progress.py")
            if "web" in parts:
                modules.add("tests/js")
            continue
        if parts[0] == "tools" and len(parts) > 2:
            name = parts[1]
            if name in IMPACT:
                modules.update(f"tests/{item}" for item in IMPACT[name])
                continue
            if name in LEAF_TEST_MODULES:
                modules.add(f"tests/{name}")
                continue
            return "FULL", []
        if parts[0] == "sources" and len(parts) > 1:
            modules.update(f"tests/{item}" for item in IMPACT["sources"])
            continue
        if parts[0] == "apple" and len(parts) > 1:
            modules.update(f"tests/{item}" for item in IMPACT["apple"])
            continue
        if parts[0] == "skills" and len(parts) > 1:
            modules.update(f"tests/{item}" for item in IMPACT["skills"])
            modules.add("tests/release/test_bundled_runtime_activation.py")
            continue
        if parts[0] == "static" and len(parts) > 1:
            modules.update(f"tests/{item}" for item in IMPACT["js"])
            continue
        return "FULL", []
    if not modules:
        return "SKIP", []
    return "SCOPED", sorted(modules)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("commit", "push"))
    args = parser.parse_args()
    try:
        paths = staged_paths() if args.phase == "commit" else pushed_paths(sys.stdin.read())
        mode, targets = select(paths)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"[test-select] Cannot classify changes: {exc}; using full suite", file=sys.stderr)
        mode, targets = "FULL", []
    print(mode)
    print(*targets, sep="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
