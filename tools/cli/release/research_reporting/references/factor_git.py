"""Validate immutable factor references against an exact Git object."""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from pathlib import Path, PurePosixPath
import re
import subprocess

from .factor_identity import (
    validate_canonical_factor_identities,
    validate_canonical_factor_identity,
)


_TARGET = re.compile(
    r"^(factor|factor-family):v1:([A-Za-z0-9._-]+):"
    r"([A-Za-z0-9_-]+):([A-Za-z0-9_-]+):"
    r"([0-9a-f]{40,64}):([0-9a-f]{40,64})$"
)


def freeze_factor_reference(
    *,
    object_kind: str,
    scope: str,
    repository: Path,
    source_file: Path,
    identity: str,
    revision: str = "HEAD",
) -> dict[str, str]:
    """Freeze an explicitly selected factor object to its current Git blob."""
    if object_kind not in {"factor", "factor-family"}:
        raise ValueError("factor object kind is invalid")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", scope):
        raise ValueError("factor reference scope is invalid")
    repository = repository.expanduser().resolve()
    source_file = source_file.expanduser().resolve()
    try:
        relative_path = source_file.relative_to(repository).as_posix()
    except ValueError as error:
        raise ValueError(
            "factor source file must be inside its registered worktree"
        ) from error
    _relative_path(relative_path)
    _git(repository, "ls-files", "--error-unmatch", "--", relative_path)
    commit = _git(repository, "rev-parse", f"{revision}^{{commit}}")
    blob = _git(repository, "rev-parse", f"{commit}:{relative_path}")
    current_blob = _git(repository, "hash-object", "--", relative_path)
    if current_blob != blob:
        raise ValueError(
            "factor source differs from the selected Git revision; commit it first"
        )
    validate_canonical_factor_identity(
        source_file=source_file,
        identity=identity,
        object_kind=object_kind,
        blob_hash=blob,
    )
    target_ref = (
        f"{object_kind}:v1:{scope}:{_encode(relative_path)}:"
        f"{_encode(identity)}:{commit}:{blob}"
    )
    validated = validate_factor_reference(
        kind="factor",
        target_ref=target_ref,
        roots={scope: repository},
    )
    return {
        "kind": "factor",
        "object_kind": object_kind,
        "target_ref": target_ref,
        **validated,
    }


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


def validate_frozen_factor_identity(
    *, target_ref: str, roots: dict[str, Path],
) -> dict[str, str]:
    """Validate Git identity and canonical executable alias for new reuse."""
    value = validate_factor_reference(
        kind="factor", target_ref=target_ref, roots=roots,
    )
    repository = roots[value["scope"]].expanduser().resolve()
    validate_canonical_factor_identity(
        source_file=repository / value["relative_path"],
        identity=value["identity"],
        object_kind=target_ref.split(":", 1)[0],
        blob_hash=value["blob_hash"],
    )
    return value


def validate_frozen_factor_identities(
    *, target_refs: list[str], roots: dict[str, Path],
) -> list[dict[str, str]]:
    """Validate a bounded factor-reference batch in one engine process."""
    values: list[dict[str, str]] = []
    requests = []
    for target_ref in target_refs:
        value = validate_factor_reference(
            kind="factor", target_ref=target_ref, roots=roots,
        )
        repository = roots[value["scope"]].expanduser().resolve()
        values.append(value)
        requests.append({
            "source_file": str(repository / value["relative_path"]),
            "identity": value["identity"],
            "object_kind": target_ref.split(":", 1)[0],
            "blob_hash": value["blob_hash"],
        })
    validate_canonical_factor_identities(requests)
    return values


def _decode(value: str) -> str:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = urlsafe_b64decode(value + padding).decode("utf-8")
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("factor reference contains invalid encoded text") from error
    if not decoded:
        raise ValueError("factor reference contains empty encoded text")
    return decoded


def _encode(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("factor reference contains empty encoded text")
    return urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


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
