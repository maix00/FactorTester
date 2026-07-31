"""Create and validate immutable Git-backed sets of factor expressions."""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any

from .factor_git import validate_factor_reference


_SET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TARGET = re.compile(
    r"^factor-set:v1:([A-Za-z0-9._-]+):"
    r"([A-Za-z0-9_-]+):([A-Za-z0-9_-]+):"
    r"([0-9a-f]{40,64}):([0-9a-f]{40,64})$"
)


def create_factor_set_manifest(
    *,
    repository: Path,
    scope: str,
    set_id: str,
    title_zh: str,
    member_refs: list[str],
    replace: bool = False,
) -> dict[str, Any]:
    """Materialize one canonical factor-set manifest without committing it."""
    _validate_set_id(set_id)
    title = title_zh.strip()
    if not title or len(title.encode("utf-8")) > 128:
        raise ValueError("factor-set title_zh must be a short non-empty title")
    members = _members(member_refs)
    path = factor_set_manifest_path(repository, set_id)
    if path.exists() and not replace:
        raise ValueError("factor-set already exists; pass --replace to update it")
    manifest = {
        "schema_version": 1,
        "set_id": set_id,
        "set_ref": f"factor-set:{scope}:{set_id}",
        "title_zh": title,
        "member_refs": members,
        "member_hash": _member_hash(members),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {**manifest, "manifest_path": str(path)}


def freeze_factor_set_reference(
    *,
    repository: Path,
    scope: str,
    set_id: str,
    roots: dict[str, Path],
    revision: str = "HEAD",
) -> dict[str, Any]:
    """Freeze one committed manifest and validate every direct factor member."""
    _validate_set_id(set_id)
    repository = repository.expanduser().resolve()
    relative_path = factor_set_manifest_path(
        repository, set_id,
    ).relative_to(repository).as_posix()
    _git(repository, "ls-files", "--error-unmatch", "--", relative_path)
    commit = _git(repository, "rev-parse", f"{revision}^{{commit}}")
    blob = _git(repository, "rev-parse", f"{commit}:{relative_path}")
    current_blob = _git(repository, "hash-object", "--", relative_path)
    if current_blob != blob:
        raise ValueError(
            "factor-set manifest differs from the selected Git revision; "
            "commit it first"
        )
    target_ref = (
        f"factor-set:v1:{scope}:{_encode(relative_path)}:{_encode(set_id)}:"
        f"{commit}:{blob}"
    )
    return validate_factor_set_reference(
        kind="factor", target_ref=target_ref, roots=roots,
    )


def validate_factor_set_reference(
    *, kind: str, target_ref: str, roots: dict[str, Path],
) -> dict[str, Any]:
    """Validate set identity, exact manifest blob, and all frozen members."""
    match = _TARGET.fullmatch(target_ref)
    if kind != "factor" or match is None:
        raise ValueError("factor-set reference kind or format is invalid")
    scope, encoded_path, encoded_set_id = match.group(1, 2, 3)
    revision, expected_blob = match.group(4, 5)
    repository = roots.get(scope)
    if repository is None:
        raise ValueError(f"factor-set reference scope is unavailable: {scope}")
    repository = repository.expanduser().resolve()
    relative_path = _relative_path(_decode(encoded_path))
    set_id = _decode(encoded_set_id)
    _validate_set_id(set_id)
    expected_path = factor_set_manifest_path(
        repository, set_id,
    ).relative_to(repository).as_posix()
    if relative_path != expected_path:
        raise ValueError("factor-set manifest path does not match its set_id")
    _git(repository, "cat-file", "-e", f"{revision}^{{commit}}")
    observed_blob = _git(repository, "rev-parse", f"{revision}:{relative_path}")
    if observed_blob != expected_blob:
        raise ValueError("factor-set manifest blob does not match its revision")
    raw = _git(repository, "show", f"{revision}:{relative_path}")
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("factor-set manifest is not valid JSON") from error
    members = _validate_manifest(
        manifest, scope=scope, set_id=set_id, roots=roots,
    )
    return {
        "kind": "factor",
        "object_kind": "factor-set",
        "target_ref": target_ref,
        "set_ref": manifest["set_ref"],
        "set_id": set_id,
        "title_zh": manifest["title_zh"],
        "member_refs": members,
        "member_hash": manifest["member_hash"],
        "member_count": len(members),
        "scope": scope,
        "relative_path": relative_path,
        "revision": revision,
        "blob_hash": observed_blob,
    }


def factor_set_manifest_path(repository: Path, set_id: str) -> Path:
    _validate_set_id(set_id)
    return repository.expanduser().resolve() / ".factortester" / "factor-sets" / (
        f"{set_id}.json"
    )


def _validate_manifest(
    value: Any,
    *,
    scope: str,
    set_id: str,
    roots: dict[str, Path],
) -> list[str]:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("factor-set manifest schema is invalid")
    if value.get("set_id") != set_id:
        raise ValueError("factor-set manifest set_id is invalid")
    if value.get("set_ref") != f"factor-set:{scope}:{set_id}":
        raise ValueError("factor-set manifest stable identity is invalid")
    title = value.get("title_zh")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("factor-set manifest title_zh is invalid")
    members = _members(value.get("member_refs"))
    if value.get("member_hash") != _member_hash(members):
        raise ValueError("factor-set member hash is invalid")
    for member_ref in members:
        if member_ref.startswith("factor-set:"):
            raise ValueError("nested factor-sets are not supported")
        validate_factor_reference(
            kind="factor", target_ref=member_ref, roots=roots,
        )
    return members


def _members(value: Any) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > 1024:
        raise ValueError("factor-set must contain 1 to 1024 factor members")
    if not all(isinstance(item, str) and item for item in value):
        raise ValueError("factor-set members must be factor references")
    if len(set(value)) != len(value):
        raise ValueError("factor-set members must be unique")
    return sorted(value)


def _member_hash(members: list[str]) -> str:
    payload = json.dumps(
        members, ensure_ascii=False, separators=(",", ":"), sort_keys=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _validate_set_id(value: str) -> None:
    if not isinstance(value, str) or _SET_ID.fullmatch(value) is None:
        raise ValueError("factor-set set_id is invalid")


def _decode(value: str) -> str:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = urlsafe_b64decode(value + padding).decode("utf-8")
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("factor-set reference contains invalid text") from error
    if not decoded:
        raise ValueError("factor-set reference contains empty text")
    return decoded


def _encode(value: str) -> str:
    return urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ValueError("factor-set reference path is invalid")
    return path.as_posix()


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False, capture_output=True, text=True,
    )
    if result.returncode:
        message = result.stderr.strip() or "Git object is unavailable"
        raise ValueError(f"factor-set Git validation failed: {message}")
    return result.stdout.strip()
