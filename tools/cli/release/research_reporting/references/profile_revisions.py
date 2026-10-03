"""Content-addressed snapshots for immutable local Profile configuration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from tools.cli.release.locations import validate_client_root
from tools.cli.release.local_profile_contracts import validate_local_profile
from tools.cli.release.storage import read_json, write_json


_TARGET = re.compile(
    r"^profile-revision:v1:([a-z0-9][a-z0-9._-]{0,63}):"
    r"sha256:([0-9a-f]{64})$"
)


class ProfileRevisionStore:
    def __init__(self, client_root: Path) -> None:
        self.root = validate_client_root(client_root) / "profile-revisions"

    def freeze(self, profile: dict[str, Any]) -> dict[str, Any]:
        normalized = validate_local_profile(profile)
        configuration = normalized
        digest = _digest(configuration)
        profile_id = str(normalized["profile_id"])
        target_ref = (
            f"profile-revision:v1:{profile_id}:sha256:{digest}"
        )
        snapshot = {
            "schema_version": 1,
            "target_ref": target_ref,
            "profile_id": profile_id,
            "configuration": configuration,
        }
        path = self._path(profile_id, digest)
        write_json(path, snapshot)
        path.chmod(0o600)
        return {**snapshot, "path": str(path)}

    def load(self, target_ref: str) -> dict[str, Any]:
        match = _TARGET.fullmatch(target_ref)
        if match is None:
            raise ValueError("profile revision reference is invalid")
        profile_id, digest = match.groups()
        snapshot = read_json(self._path(profile_id, digest))
        if not isinstance(snapshot, dict):
            raise ValueError("profile revision is not registered locally")
        if (
            snapshot.get("target_ref") != target_ref
            or snapshot.get("profile_id") != profile_id
            or _digest(snapshot.get("configuration")) != digest
        ):
            raise ValueError("profile revision snapshot is invalid")
        return snapshot

    def _path(self, profile_id: str, digest: str) -> Path:
        return self.root / profile_id / f"{digest}.json"


def _digest(value: Any) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
