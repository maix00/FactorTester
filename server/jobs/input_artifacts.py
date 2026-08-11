"""Retained, immutable input files owned by one JobAttempt."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

from server.jobs.artifacts import artifact_root, resolve_artifact_path


FACTOR_SOURCE_PREFIX = "factor_source__"
STRATEGY_SOURCE_PREFIX = "strategy_source__"
STRATEGY_SPEC_PREFIX = "strategy_spec__"


def factor_source_artifact_name(factor_id: str) -> str:
    return f"{FACTOR_SOURCE_PREFIX}{str(factor_id).strip()}"


def strategy_source_artifact_name(source_path: str) -> str:
    digest = hashlib.sha256(str(source_path).encode("utf-8")).hexdigest()[:20]
    return f"{STRATEGY_SOURCE_PREFIX}{digest}"


def strategy_spec_artifact_name(content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()[:20]
    return f"{STRATEGY_SPEC_PREFIX}{digest}"


def _strategy_spec_label(spec: dict[str, Any]) -> str:
    return str(
        spec.get("strategy_id")
        or spec.get("source_name")
        or spec.get("source")
        or "strategy"
    ).strip()


def _safe_strategy_spec_file_name(label: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-.")
    return f"{stem or 'strategy'}.strategy.json"


def canonical_strategy_spec_content(spec: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            spec,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def strategy_spec_input_bytes(entries: Iterable[dict[str, Any]]) -> int:
    return sum(len(canonical_strategy_spec_content(entry)) for entry in entries)


def artifact_role(metadata: dict[str, Any]) -> str:
    role = str(metadata.get("artifact_role") or "output")
    return role if role in {"input", "output"} else "output"


def retain_input_files(
    repository: Any,
    *,
    job_id: str,
    owner: str,
    entries: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Persist validated Job inputs beside output artifacts."""
    values = list(entries)
    if not values:
        return []
    root = artifact_root()
    directory = root / str(job_id) / "inputs"
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    stored: list[dict[str, Any]] = []
    try:
        for entry in values:
            file_name = Path(str(entry["file_name"])).name
            if not file_name or file_name != str(entry["file_name"]):
                raise ValueError("Job input file_name must be a base name")
            raw = bytes(entry["content"])
            digest = hashlib.sha256(raw).hexdigest()
            expected_hash = str(entry.get("content_hash") or digest)
            if digest != expected_hash:
                raise ValueError("Job input hash changed before retention")
            kind = str(entry["artifact_kind"]).strip()
            target_directory = directory / kind
            target_directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            storage_name = Path(
                str(entry.get("storage_name") or file_name)
            ).name
            if not storage_name:
                raise ValueError("Job input storage_name must be a base name")
            target = target_directory / storage_name
            staging = target_directory / f".{storage_name}.{os.getpid()}.tmp"
            staging.write_bytes(raw)
            staging.chmod(0o600)
            os.replace(staging, target)
            stored.append(repository.record_artifact(
                job_id=job_id,
                name=str(entry["name"]),
                relative_path=str(target.relative_to(root)),
                content_type=str(entry["content_type"]),
                content_hash=digest,
                size_bytes=len(raw),
                retention_mode="retained",
                artifact_role="input",
                artifact_kind=kind,
                file_name=file_name,
                logical_path=str(entry.get("logical_path") or file_name),
                title_zh=str(entry.get("title_zh") or file_name),
            ))
    except Exception:
        for metadata in repository.mark_artifacts_deleted(
            job_id=job_id, owner=owner,
        ):
            try:
                path = root / str(metadata["relative_path"])
                if root in path.resolve().parents:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    return stored


def retain_factor_sources(
    repository: Any,
    *,
    job_id: str,
    owner: str,
    entries: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Copy validated transient sources into the Job's retained file set."""
    return retain_input_files(
        repository,
        job_id=job_id,
        owner=owner,
        entries=[{
            "name": factor_source_artifact_name(str(entry["factor_id"])),
            "artifact_kind": "factor_source",
            "file_name": f"{entry['factor_id']}.py",
            "logical_path": str(entry["path"]),
            "title_zh": f"临时因子源码：{entry['factor_id']}",
            "content_type": "text/x-python",
            "content": str(entry["source_code"]).encode("utf-8"),
            "content_hash": str(entry["source_sha256"]),
        } for entry in entries],
    )


def retain_strategy_sources(
    repository: Any,
    *,
    job_id: str,
    owner: str,
    entries: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    return retain_input_files(
        repository,
        job_id=job_id,
        owner=owner,
        entries=[{
            "name": strategy_source_artifact_name(str(entry["path"])),
            "artifact_kind": "strategy_source",
            "file_name": Path(str(entry["path"])).name,
            "logical_path": str(entry["path"]),
            "storage_name": (
                strategy_source_artifact_name(str(entry["path"])) + ".py"
            ),
            "title_zh": f"临时策略源码：{entry['path']}",
            "content_type": "text/x-python",
            "content": str(entry["source_code"]).encode("utf-8"),
            "content_hash": hashlib.sha256(
                str(entry["source_code"]).encode("utf-8")
            ).hexdigest(),
        } for entry in entries],
    )


def retain_strategy_specs(
    repository: Any,
    *,
    job_id: str,
    owner: str,
    entries: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Retain canonical StrategySpec inputs exactly as frozen by RunSpec."""
    prepared: list[dict[str, Any]] = []
    for entry in entries:
        content = canonical_strategy_spec_content(entry)
        label = _strategy_spec_label(entry)
        file_name = _safe_strategy_spec_file_name(label)
        if not str(entry.get("strategy_id") or "").strip():
            suffix = hashlib.sha256(content).hexdigest()[:8]
            file_name = file_name.removesuffix(".strategy.json")
            file_name = f"{file_name}-{suffix}.strategy.json"
        artifact_name = strategy_spec_artifact_name(content)
        prepared.append({
            "name": artifact_name,
            "artifact_kind": "strategy_spec",
            "file_name": file_name,
            "storage_name": f"{artifact_name}.json",
            "logical_path": f"strategy-specs/{file_name}",
            "title_zh": f"运行策略配置：{label}",
            "content_type": "application/json",
            "content": content,
            "content_hash": hashlib.sha256(content).hexdigest(),
        })
    return retain_input_files(
        repository,
        job_id=job_id,
        owner=owner,
        entries=prepared,
    )


def load_retained_factor_sources(
    repository: Any,
    *,
    job_id: str,
    owner: str,
) -> list[dict[str, Any]]:
    """Reconstruct transient entries from retained Job input artifacts."""
    entries: list[dict[str, Any]] = []
    for metadata in repository.list_artifacts(job_id=job_id, owner=owner):
        name = str(metadata.get("name") or "")
        if (
            artifact_role(metadata) != "input"
            or str(metadata.get("artifact_kind") or "") != "factor_source"
            or metadata.get("state") != "active"
            or not name.startswith(FACTOR_SOURCE_PREFIX)
        ):
            continue
        factor_id = name[len(FACTOR_SOURCE_PREFIX):]
        path = resolve_artifact_path(
            str(metadata["relative_path"]),
            expected_hash=str(metadata["content_hash"]),
        )
        source_code = path.read_text(encoding="utf-8")
        entries.append({
            "factor_id": factor_id,
            "path": f"custom_factors/{factor_id}.py",
            "source_code": source_code,
            "source_sha256": str(metadata["content_hash"]),
            "source_bytes": int(metadata["size_bytes"]),
        })
    return sorted(entries, key=lambda item: item["factor_id"])


def load_retained_strategy_sources(
    repository: Any,
    *,
    job_id: str,
    owner: str,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for metadata in repository.list_artifacts(job_id=job_id, owner=owner):
        if (
            artifact_role(metadata) != "input"
            or str(metadata.get("artifact_kind") or "") != "strategy_source"
            or metadata.get("state") != "active"
        ):
            continue
        path = resolve_artifact_path(
            str(metadata["relative_path"]),
            expected_hash=str(metadata["content_hash"]),
        )
        entries.append({
            "path": str(metadata["logical_path"]),
            "source_code": path.read_text(encoding="utf-8"),
        })
    return sorted(entries, key=lambda item: item["path"])
