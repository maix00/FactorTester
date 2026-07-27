"""Download Job outputs and mount report-ready tables and images locally."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
from typing import Any

from .document import (
    add_asset,
    add_binding,
    add_component,
    bindings_path_for,
    load_bindings,
    load_document,
    save_bindings,
    save_document,
)


_IMAGE_TYPES = {
    "image/svg+xml": ".svg",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
_TABLE_TYPES = {"text/csv", "application/json"}
_TABLE_NAMES = {
    "equity_curve_data",
    "returns_over_time_data",
    "metrics_over_time_data",
    "fee_detail_csv",
    "fee_detail_data",
    "margin_detail_csv",
    "margin_detail_data",
    "ratio_detail_csv",
    "ratio_detail_data",
}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_TABLE_ROWS = 4096
_MAX_TABLE_COLUMNS = 32


def collect_job_report(
    client: Any,
    *,
    job_id: str,
    report_file: Path,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Download every active artifact and mount only tables/images.

    The server owns immutable Job evidence.  This function owns the local
    report projection: all files are retained in the Job directory, while
    only report-ready statistical tables and images become special sections.
    """
    detail = client.get_job(job_id)
    status = str((detail.get("status") or (detail.get("job") or {}).get("status") or "").lower())
    if status not in {"succeeded", "failed", "cancelled"}:
        raise ValueError(f"Job 尚未结束，不能收集报告生成物: {status or 'unknown'}")
    report_path = Path(report_file).expanduser().resolve()
    document = load_document(report_path)
    bindings_file = bindings_path_for(report_path)
    bindings = load_bindings(bindings_file, document)
    if output_dir is None:
        workspace_id = str(
            detail.get("workspace_id")
            or (detail.get("job") or {}).get("workspace_id")
            or "unknown"
        )
        output_dir = (
            Path.home() / ".factortester" / "workspaces" / workspace_id
            / "jobs" / str(job_id)
        )
    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    artifacts = client.list_job_artifacts(job_id)
    mounted: list[dict[str, Any]] = []
    downloaded: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for metadata in artifacts:
        if str(metadata.get("state") or "active") != "active":
            continue
        name = str(metadata.get("name") or "artifact")
        filename = _download_name(metadata)
        target = output_root / filename
        raw = _download(client, job_id, name, target)
        downloaded.append({
            "name": name,
            "path": str(target),
            "content_hash": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
        })
        kind = _mount_kind(name, metadata)
        if kind is None:
            skipped.append({"name": name, "reason": "不是统计表格或图片"})
            continue
        try:
            document, bindings, item = _mount(
                document=document,
                bindings=bindings,
                report_path=report_path,
                job_id=str(job_id),
                detail=detail,
                metadata=metadata,
                raw=raw,
                source_path=target,
                kind=kind,
            )
        except (TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            skipped.append({"name": name, "reason": f"无法挂载: {exc}"})
            continue
        mounted.append(item)

    save_document(report_path, document)
    save_bindings(bindings_file, bindings, document)
    return {
        "job_id": str(job_id),
        "status": status,
        "report_file": str(report_path),
        "job_output_dir": str(output_root),
        "downloaded": downloaded,
        "mounted": mounted,
        "skipped": skipped,
        "mount_policy": {
            "included": ["statistical_table", "image"],
            "excluded": ["log", "raw", "debug", "archive", "receipt"],
        },
    }


def _download_name(metadata: dict[str, Any]) -> str:
    value = Path(str(metadata.get("file_name") or metadata.get("name") or "artifact")).name
    if not value or value in {".", ".."}:
        value = "artifact"
    if Path(value).suffix:
        return value
    mime = str(metadata.get("content_type") or "").split(";", 1)[0].lower()
    extension = _IMAGE_TYPES.get(mime) or {
        "application/json": ".json",
        "text/csv": ".csv",
        "text/plain": ".txt",
    }.get(mime, "")
    return value + extension


def _download(client: Any, job_id: str, name: str, target: Path) -> bytes:
    response = client.job_artifact(job_id, name)
    raw = bytes(response.content)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.{os.getpid()}.part")
    staging.write_bytes(raw)
    staging.replace(target)
    return raw


def _mount_kind(name: str, metadata: dict[str, Any]) -> str | None:
    mime = str(metadata.get("content_type") or "").split(";", 1)[0].lower()
    if mime in _IMAGE_TYPES:
        return "image"
    if name in _TABLE_NAMES and mime in _TABLE_TYPES:
        return "table"
    return None


def _mount(
    *,
    document: dict[str, Any],
    bindings: dict[str, Any],
    report_path: Path,
    job_id: str,
    detail: dict[str, Any],
    metadata: dict[str, Any],
    raw: bytes,
    source_path: Path,
    kind: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    name = str(metadata.get("name") or "artifact")
    digest = hashlib.sha256(raw).hexdigest()
    component_id = _component_id(job_id, name, digest)
    existing = {item["component_id"] for item in document["components"]}
    if component_id not in existing:
        title = str(metadata.get("description") or name)
        if kind == "image":
            asset = _stage_image(report_path, raw, metadata, digest)
            if not any(item["asset_ref"] == asset["asset_ref"] for item in document["assets"]):
                document = add_asset(document, asset)
            content = {"asset_ref": asset["asset_ref"]}
            display_kind = "job-artifact-image"
        else:
            content = _table_content(raw, metadata)
            display_kind = "job-artifact-table"
        document = add_component(
            document,
            component_id=component_id,
            kind="special",
            title=title,
            parent_id=_parent_id(document),
            body=f"Job {job_id} · {name}",
            content=content,
            display_kind=display_kind,
        )
    bindings = _add_provenance_bindings(
        bindings, document, component_id=component_id,
        job_id=job_id, detail=detail, digest=digest,
    )
    return document, bindings, {
        "name": name,
        "component_id": component_id,
        "kind": kind,
        "content_hash": digest,
        "source_path": str(source_path),
    }


def _stage_image(
    report_path: Path, raw: bytes, metadata: dict[str, Any], digest: str,
) -> dict[str, str]:
    mime = str(metadata.get("content_type") or "").split(";", 1)[0].lower()
    extension = _IMAGE_TYPES[mime]
    if mime == "image/svg+xml":
        _validate_passive_svg(raw)
    filename = f"{digest}{extension}"
    directory = report_path.parent / "assets"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    if target.exists() and target.read_bytes() != raw:
        raise ValueError("本地报告图片存在同名不同内容")
    if not target.exists():
        staging = target.with_name(f".{filename}.{os.getpid()}.part")
        staging.write_bytes(raw)
        staging.replace(target)
    return {
        "asset_ref": f"report-asset:sha256:{digest}",
        "media_type": mime,
        "filename": filename,
        "caption": str(metadata.get("description") or metadata.get("name") or ""),
        "alt_text": str(metadata.get("description") or "Job image"),
    }


def _validate_passive_svg(raw: bytes) -> None:
    text = raw.decode("utf-8")
    lowered = text.lower()
    forbidden = ("<script", "<foreignobject", "<!doctype", "<!entity", "javascript:")
    if not lowered.lstrip().startswith("<svg") or any(item in lowered for item in forbidden):
        raise ValueError("SVG 含有主动内容")
    if re.search(r"(?:href|src)\s*=\s*[\"']\s*(?:https?:|file:|javascript:)", lowered):
        raise ValueError("SVG 含有外部引用")
    if re.search(r"\son[a-z]+\s*=", lowered):
        raise ValueError("SVG 含有事件处理器")


def _table_content(raw: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    mime = str(metadata.get("content_type") or "").split(";", 1)[0].lower()
    if mime == "text/csv":
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        if not rows:
            raise ValueError("CSV 为空")
        columns = rows[0]
        values = rows[1:]
    else:
        payload = json.loads(raw.decode("utf-8"))
        columns, values = _json_rows(payload)
    if not isinstance(columns, list) or not columns:
        raise ValueError("统计表缺少列")
    columns = [str(item)[:256] for item in columns[:_MAX_TABLE_COLUMNS]]
    width = len(columns)
    normalized = []
    for row in values[:_MAX_TABLE_ROWS]:
        if isinstance(row, dict):
            row = [row.get(column, "") for column in columns]
        if not isinstance(row, list):
            raise ValueError("统计表行格式无效")
        normalized.append([str(item)[:2048] for item in row[:width]] + [""] * max(0, width - len(row)))
    return {"columns": columns, "rows": normalized}


def _json_rows(value: Any) -> tuple[list[str], list[list[Any]]]:
    if isinstance(value, dict) and isinstance(value.get("columns"), list) and isinstance(value.get("rows"), list):
        return list(value["columns"]), list(value["rows"])
    if isinstance(value, dict) and isinstance(value.get("rows"), list):
        return _json_rows(value["rows"])
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        columns = list(dict.fromkeys(str(key) for item in value for key in item))
        return columns, [[item.get(column, "") for column in columns] for item in value]
    if isinstance(value, dict):
        return ["key", "value"], [[key, item] for key, item in value.items()]
    if isinstance(value, list):
        return ["value"], [[item] for item in value]
    return ["value"], [[value]]


def _parent_id(document: dict[str, Any]) -> str | None:
    chapters = [item for item in document["components"] if item["kind"] == "chapter"]
    return chapters[0]["component_id"] if chapters else None


def _component_id(job_id: str, name: str, digest: str) -> str:
    raw = _SAFE_NAME.sub("-", f"job-{job_id}-{name}").strip("-")
    return (raw[:104] + "-" + digest[:16])[:128]


def _add_provenance_bindings(
    bindings: dict[str, Any], document: dict[str, Any], *,
    component_id: str, job_id: str, detail: dict[str, Any], digest: str,
) -> dict[str, Any]:
    evidence = ((detail.get("evidence") or {}).get("job_attempt") or {})
    evidence_hash = str(evidence.get("envelope_hash") or "")
    evidence_ref = (
        f"evidence:job_attempt:sha256:{evidence_hash}"
        if re.fullmatch(r"[0-9a-f]{64}", evidence_hash)
        else f"research-job:{job_id}"
    )
    base = [
        ("evidence", f"evidence-{job_id}-{digest[:12]}", evidence_ref, "Job 终态证据"),
        ("job", f"job-{job_id}-{digest[:12]}", f"research-job:{job_id}", "Job 来源"),
    ]
    binding_ids = {item["binding_id"] for item in bindings["bindings"]}
    for kind, binding_id, target_ref, label in base:
        if binding_id in binding_ids:
            continue
        bindings = add_binding(
            bindings, document, component_id=component_id,
            binding_id=binding_id, kind=kind, target_ref=target_ref,
            label=label, data={"content_hash": digest},
        )
    return bindings
