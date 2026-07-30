"""Validate immutable factor references against an exact Git object."""

from __future__ import annotations

from base64 import urlsafe_b64decode
from pathlib import Path, PurePosixPath
import re
import subprocess


_TARGET = re.compile(
    r"^(factor|factor-family):v1:([A-Za-z0-9._-]+):"
    r"([A-Za-z0-9_-]+):([A-Za-z0-9_-]+):"
    r"([0-9a-f]{40,64}):([0-9a-f]{40,64})$"
)


def validate_factor_reference(
    *,
    kind: str,
    target_ref: str,
    roots: dict[str, Path],
) -> dict[str, str]:
    """Verify scope, path, commit, and blob without reading current prose."""
    match = _TARGET.fullmatch(target_ref)
    if (
        kind != "factor"
        or match is None
        or match.group(1) not in {"factor", "factor-family"}
    ):
        raise ValueError("factor reference kind or format is invalid")
    scope, encoded_path, encoded_identity = match.group(2, 3, 4)
    revision, expected_blob = match.group(5, 6)
    repository = roots.get(scope)
    if repository is None:
        raise ValueError(f"factor reference scope is unavailable: {scope}")
    relative_path = _relative_path(_decode(encoded_path))
    identity = _decode(encoded_identity)
    _git(repository, "cat-file", "-e", f"{revision}^{{commit}}")
    observed_blob = _git(
        repository, "rev-parse", f"{revision}:{relative_path}",
    )
    if observed_blob != expected_blob:
        raise ValueError("factor reference blob does not match its revision")
    return {
        "scope": scope,
        "relative_path": relative_path,
        "identity": identity,
        "revision": revision,
        "blob_hash": observed_blob,
    }


def _decode(value: str) -> str:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = urlsafe_b64decode(value + padding).decode("utf-8")
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("factor reference contains invalid encoded text") from error
    if not decoded:
        raise ValueError("factor reference contains empty encoded text")
    return decoded


def _relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ValueError("factor reference path is invalid")
    return path.as_posix()


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False, capture_output=True, text=True,
    )
    if result.returncode:
        message = result.stderr.strip() or "Git object is unavailable"
        raise ValueError(f"factor reference Git validation failed: {message}")
    return result.stdout.strip()
