"""Bounded, principal-scoped inventory of server Profile workspace bytes.

This is a local storage measurement, not a cross-server quota projection.
Callers must keep the server identity and observation time with the result.
"""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path
from typing import Any

from tools.cli.release.local_profile_contracts import validate_principal_identifier


class ProfileStorageInventoryIncomplete(RuntimeError):
    """Measurement stopped rather than silently presenting a partial total."""


def scan_profile_storage(
    data_root: str | Path,
    principal: str,
    *,
    max_files: int = 250_000,
    max_seconds: float = 10.0,
) -> dict[str, Any]:
    """Measure one principal's server Profile files without following links.

    Hard links inside the scoped tree are counted once. Logical file sizes are
    reported; a filesystem capacity guard must use statvfs separately.
    """
    owner = validate_principal_identifier(principal, "principal")
    root_base = Path(data_root).expanduser().resolve()
    root = root_base / "users" / owner / "profiles"
    if max_files < 1 or max_seconds <= 0:
        raise ValueError("Profile inventory limits must be positive")
    observed_at = time.time()
    result: dict[str, Any] = {
        "observed_at": observed_at,
        "categories": {
            "research_reports": {"bytes": 0, "file_count": 0},
            "profile_uploads": {"bytes": 0, "file_count": 0},
            "profile_workspaces": {"bytes": 0, "file_count": 0},
        },
        "file_count": 0,
        "bytes": 0,
    }
    if any(path.is_symlink() for path in (
        root_base / "users", root_base / "users" / owner, root,
    )):
        raise ProfileStorageInventoryIncomplete("Profile root contains a symlink")
    if not root.exists():
        return result
    if not root.is_dir():
        raise ProfileStorageInventoryIncomplete("Profile root is not a directory")
    started = time.monotonic()
    seen: dict[tuple[int, int], tuple[str, int]] = {}
    category_priority = {
        "profile_workspaces": 0, "profile_uploads": 1, "research_reports": 2,
    }
    stack = [root]
    try:
        while stack:
            if time.monotonic() - started > max_seconds:
                raise ProfileStorageInventoryIncomplete("Profile inventory time limit reached")
            directory = stack.pop()
            with os.scandir(directory) as entries:
                ordered = sorted(entries, key=lambda item: item.name)
            for index, entry in enumerate(ordered):
                if index % 1000 == 0 and time.monotonic() - started > max_seconds:
                    raise ProfileStorageInventoryIncomplete(
                        "Profile inventory time limit reached"
                    )
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                    continue
                metadata = entry.stat(follow_symlinks=False)
                if not stat.S_ISREG(metadata.st_mode):
                    continue
                result["file_count"] += 1
                if result["file_count"] > max_files:
                    raise ProfileStorageInventoryIncomplete(
                        "Profile inventory file limit reached"
                    )
                inode = (metadata.st_dev, metadata.st_ino)
                relative = Path(entry.path).relative_to(root)
                category = "profile_workspaces"
                if len(relative.parts) >= 2:
                    if relative.parts[1] in {"research", "reports"}:
                        category = "research_reports"
                    elif relative.parts[1] == "uploads":
                        category = "profile_uploads"
                previous = seen.get(inode)
                if previous is not None:
                    old_category, size = previous
                    if category_priority[category] > category_priority[old_category]:
                        result["categories"][old_category]["bytes"] -= size
                        result["categories"][old_category]["file_count"] -= 1
                        result["categories"][category]["bytes"] += size
                        result["categories"][category]["file_count"] += 1
                        seen[inode] = (category, size)
                    continue
                seen[inode] = (category, metadata.st_size)
                result["categories"][category]["bytes"] += metadata.st_size
                result["categories"][category]["file_count"] += 1
                result["bytes"] += metadata.st_size
    except OSError as exc:
        raise ProfileStorageInventoryIncomplete(
            "Profile inventory could not read all files"
        ) from exc
    return result
