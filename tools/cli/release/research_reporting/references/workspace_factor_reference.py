"""Create formula references from an optionally Git-managed workspace."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import re
import subprocess
from tempfile import TemporaryDirectory

from tools.cli.identities.factor import (
    freeze_factor_family_identity,
    freeze_factor_identity,
)
from .factor_identity import inspect_canonical_factor_identities


def freeze_factor_reference(
    *,
    object_kind: str,
    scope: str,
    repository: Path,
    source_file: Path,
    identity: str,
    revision: str = "HEAD",
) -> dict[str, object]:
    repository = repository.expanduser().resolve()
    source_file = source_file.expanduser().resolve()
    try:
        relative_path = source_file.relative_to(repository).as_posix()
    except ValueError as error:
        raise ValueError("factor source must be inside its workspace") from error
    commit = _git(repository, "rev-parse", f"{revision}^{{commit}}")
    tracked_blob = _git(repository, "rev-parse", f"{commit}:{relative_path}")
    current_blob = _git(repository, "hash-object", "--", relative_path)
    if current_blob != tracked_blob:
        raise ValueError("factor source differs from the selected workspace revision")
    return freeze_factor_reference_at_revision(
        object_kind=object_kind,
        scope=scope,
        repository=repository,
        relative_path=relative_path,
        identity=identity,
        revision=commit,
    )


def freeze_factor_reference_at_revision(
    *,
    object_kind: str,
    scope: str,
    repository: Path,
    relative_path: str,
    identity: str,
    revision: str = "HEAD",
) -> dict[str, object]:
    if object_kind not in {"factor", "factor-family"}:
        raise ValueError("factor object kind is invalid")
    repository = repository.expanduser().resolve()
    path = _relative_path(relative_path)
    commit = _git(repository, "rev-parse", f"{revision}^{{commit}}")
    source = _git_bytes(repository, "show", f"{commit}:{path}")
    blob = _git(repository, "rev-parse", f"{commit}:{path}")
    with TemporaryDirectory(prefix="factortester-factor-formula-") as directory:
        source_file = Path(directory) / Path(path).name
        source_file.write_bytes(source)
        formula = inspect_canonical_factor_identities([{
            "source_file": str(source_file),
            "identity": identity,
            "object_kind": object_kind,
            "blob_hash": blob,
        }])[0]
    canonical = formula["canonical_identity"]
    owner_ref = _owner_ref(scope)
    family_alias = canonical.split("|", 1)[0]
    if object_kind == "factor":
        record = freeze_factor_identity(
            owner_ref=owner_ref,
            family_alias=family_alias,
            factor_alias=canonical,
            family_formula_fingerprint=formula["family_formula_fingerprint"],
            self_formula_fingerprint=formula["self_formula_fingerprint"],
            params=formula["params"],
        )
    else:
        record = freeze_factor_family_identity(
            owner_ref=owner_ref,
            family_alias=family_alias,
            family_formula_fingerprint=formula["family_formula_fingerprint"],
        )
    return {
        "kind": "factor",
        "object_kind": object_kind,
        "target_ref": record["ref"],
        "record": record,
        "owner_ref": owner_ref,
        "family_alias": family_alias,
        "factor_alias": canonical if object_kind == "factor" else "",
        "family_formula_fingerprint": formula["family_formula_fingerprint"],
        "self_formula_fingerprint": formula["self_formula_fingerprint"],
        "workspace_provenance": {
            "relative_path": path,
            "revision": commit,
            "blob_hash": blob,
        },
    }


def _owner_ref(scope: str) -> str:
    value = str(scope or "").strip()
    match = re.fullmatch(r"(profile|user|principal|org|team)-(.+)", value)
    return f"{match.group(1)}:{match.group(2)}" if match else value


def _relative_path(value: str) -> str:
    path = PurePosixPath(str(value or ""))
    if path.is_absolute() or not path.parts or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ValueError("factor source path is invalid")
    return path.as_posix()


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise ValueError(result.stderr.strip() or "workspace Git object is unavailable")
    return result.stdout.strip()


def _git_bytes(repository: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        capture_output=True,
    )
    if result.returncode:
        raise ValueError(
            result.stderr.decode("utf-8", errors="replace").strip()
            or "workspace Git object is unavailable"
        )
    return result.stdout


__all__ = ["freeze_factor_reference", "freeze_factor_reference_at_revision"]
