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
    return {
        "source": str(root),
        "owner_ref": owner,
        "manifest_sha256": sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        "git_head": _git_head(root),
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
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""
