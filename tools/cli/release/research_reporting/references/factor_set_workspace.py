"""Persist FactorSet records in an optional workspace without Git identity."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from tools.factors.factor_set_identity import (
    freeze_factor_set_identity,
    require_factor_set_reference,
    require_frozen_factor_set,
)

_SET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def create_factor_set_manifest(
    *,
    repository: Path,
    scope: str,
    set_id: str,
    title_zh: str,
    members: list[dict[str, Any]],
    description_zh: str = "",
    replace: bool = False,
    expected_member_fingerprint: str = "",
) -> dict[str, Any]:
    """Write one complete frozen FactorSet record atomically."""
    _validate_set_id(set_id)
    description = str(description_zh or "").strip()
    if len(description.encode()) > 512:
        raise ValueError("factor-set description is too long")
    frozen = freeze_factor_set_identity(
        owner_ref=_owner_ref(scope),
        set_id=set_id,
        alias=title_zh,
        members=members,
    )
    path = factor_set_manifest_path(repository, set_id)
    if path.exists() and not replace:
        raise ValueError("factor-set already exists; pass --replace to update it")
    if path.exists() and replace:
        current = read_factor_set_manifest(
            repository=repository, scope=scope, set_id=set_id,
        )
        if not expected_member_fingerprint:
            raise ValueError(
                "factor-set replacement requires expected_member_fingerprint"
            )
        if current["identity"]["member_fingerprint"] != expected_member_fingerprint:
            raise ValueError("factor-set expected member fingerprint is stale")
    value = {**frozen, "description": description}
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(path, value)
    return {**value, "manifest_path": str(path)}


def read_factor_set_manifest(
    *, repository: Path, scope: str, set_id: str,
) -> dict[str, Any]:
    path = factor_set_manifest_path(repository, set_id)
    if not path.is_file():
        raise ValueError(f"factor-set does not exist: {set_id}")
    return _manifest_value(
        path.read_text(encoding="utf-8"),
        scope=scope,
        set_id=set_id,
        manifest_path=path,
    )


def _manifest_value(
    raw: str,
    *,
    scope: str,
    set_id: str,
    manifest_path: Path,
) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("factor-set manifest is not valid JSON") from error
    value = require_frozen_factor_set(parsed)
    if value["owner_ref"] != _owner_ref(scope):
        raise ValueError("factor-set owner does not match its workspace")
    if value["identity"]["set_id"] != set_id:
        raise ValueError("factor-set id does not match its manifest path")
    value["description"] = str(parsed.get("description") or "")
    value["manifest_path"] = str(manifest_path)
    return value


def freeze_factor_set_reference(
    *, repository: Path, scope: str, set_id: str, roots: object = None,
    revision: str = "",
) -> dict[str, Any]:
    del roots, revision
    return _projection(read_factor_set_manifest(
        repository=repository, scope=scope, set_id=set_id,
    ))


def validate_factor_set_reference(
    *, kind: str, target_ref: str, roots: dict[str, Path],
) -> dict[str, Any]:
    if kind != "factor":
        raise ValueError("factor-set reference kind is invalid")
    require_factor_set_reference(target_ref)
    for scope, repository in roots.items():
        directory = factor_set_manifest_path(repository, "placeholder").parent
        for path in sorted(directory.glob("*.json")) if directory.is_dir() else ():
            value = read_factor_set_manifest(
                repository=repository, scope=scope, set_id=path.stem,
            )
            if value["ref"] == target_ref:
                return _projection(value)
    for scope, repository in roots.items():
        value = _historical_manifest(
            repository,
            scope=scope,
            target_ref=target_ref,
        )
        if value is not None:
            return _projection(value)
    raise ValueError("factor-set ref is unavailable or ambiguous")


def _historical_manifest(
    repository: Path,
    *,
    scope: str,
    target_ref: str,
) -> dict[str, Any] | None:
    """Resolve immutable Factor Sets retained in the local Git history."""
    if not (repository / ".git").exists():
        return None
    directory = ".factortester/factor-sets"
    revisions = _git_lines(
        repository, "log", "--all", "--format=%H", "--", directory,
    )[:512]
    for revision in revisions:
        paths = _git_lines(
            repository, "ls-tree", "-r", "--name-only", revision, "--", directory,
        )
        for relative in paths:
            if not relative.endswith(".json"):
                continue
            result = subprocess.run(
                ["git", "-C", str(repository), "show", f"{revision}:{relative}"],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode:
                continue
            try:
                value = _manifest_value(
                    result.stdout,
                    scope=scope,
                    set_id=Path(relative).stem,
                    manifest_path=repository / relative,
                )
            except (TypeError, ValueError):
                continue
            if value["ref"] == target_ref:
                return value
    return None


def _git_lines(repository: Path, *arguments: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def factor_set_manifest_path(repository: Path, set_id: str) -> Path:
    _validate_set_id(set_id)
    return repository.expanduser().resolve() / ".factortester" / "factor-sets" / (
        f"{set_id}.json"
    )


def _projection(value: dict[str, Any]) -> dict[str, Any]:
    members = value["identity"]["members"]
    return {
        "kind": "factor",
        "object_class": "FactorSet",
        "target_ref": value["ref"],
        "alias": value["alias"],
        "owner_ref": value["owner_ref"],
        "set_id": value["identity"]["set_id"],
        "member_fingerprint": value["identity"]["member_fingerprint"],
        "member_count": len(members),
        "member_refs": [item["ref"] for item in members],
        "related_references": [
            {
                "relation": "集合成员",
                "kind": "factor",
                "target_ref": item["ref"],
                "label": item["alias"],
                "data": item,
            }
            for item in members
        ],
        "descriptor": value,
    }


def _owner_ref(scope: str) -> str:
    value = str(scope or "").strip()
    match = re.fullmatch(r"(profile|user|principal|org|team)-(.+)", value)
    return f"{match.group(1)}:{match.group(2)}" if match else value


def _validate_set_id(value: str) -> None:
    if not isinstance(value, str) or _SET_ID.fullmatch(value) is None:
        raise ValueError("factor-set set_id is invalid")


def _atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


__all__ = [
    "create_factor_set_manifest",
    "factor_set_manifest_path",
    "freeze_factor_set_reference",
    "read_factor_set_manifest",
    "validate_factor_set_reference",
]
