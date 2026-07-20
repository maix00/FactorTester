"""Read-only inventory for a local factor workspace migration."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any


def inventory_workspace(source: Path) -> dict[str, Any]:
    root = source.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"workspace source not found: {root}")
    manifest_path = root / ".factor_workspace" / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"factor workspace manifest not found: {root}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    owner = str(manifest.get("username") or "").strip()
    if not owner:
        raise ValueError(f"factor workspace owner is missing: {root}")
    count, size = _tree_usage(root)
    unsafe_symlinks = _unsafe_symlinks(root)
    return {
        "source": str(root),
        "owner_ref": owner,
        "manifest_sha256": sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        "git_head": _git_head(root),
        "git_branch": _git_value(root, "branch", "--show-current"),
        "git_refs_sha256": _git_refs_digest(root),
        "tree_sha256": _tree_digest(root),
        "unsafe_symlinks": unsafe_symlinks,
        "has_git": (root / ".git").exists(),
        "has_vscode": (root / ".vscode").is_dir(),
        "has_pyright_config": (root / "pyrightconfig.json").is_file(),
        "file_count": count,
        "bytes": size,
    }


def available_bytes(path: Path) -> int:
    candidate = path.expanduser().resolve()
    while not candidate.exists():
        candidate = candidate.parent
    return shutil.disk_usage(candidate).free


def _tree_usage(root: Path) -> tuple[int, int]:
    count = 0
    size = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_file():
            count += 1
            size += path.stat().st_size
    return count, size


def _git_head(root: Path) -> str:
    return _git_value(root, "rev-parse", "HEAD")


def _git_value(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _git_refs_digest(root: Path) -> str:
    refs = _git_value(root, "show-ref")
    return sha256(refs.encode()).hexdigest() if refs else ""


def _unsafe_symlinks(root: Path) -> list[str]:
    unsafe = []
    for path in root.rglob("*"):
        if not path.is_symlink():
            continue
        try:
            path.resolve(strict=False).relative_to(root)
        except ValueError:
            unsafe.append(str(path.relative_to(root)))
    return sorted(unsafe)


def _tree_digest(root: Path) -> str:
    digest = sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts[:1] == (".git",):
            continue
        digest.update(str(relative).encode())
        if path.is_symlink():
            digest.update(b"link:")
            digest.update(str(path.readlink()).encode())
        elif path.is_file():
            digest.update(b"file:")
            digest.update(path.read_bytes())
    return digest.hexdigest()
