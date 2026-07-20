"""Bounded, source-free research report snapshot validation."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any


MAX_SNAPSHOT_BYTES = 64 * 1024
MAX_REPORT_BYTES = 128 * 1024
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROHIBITED_KEYS = {
    "credentials",
    "expression_tree",
    "factor_source",
    "formula",
    "raw_stderr",
    "raw_stdout",
    "source_code",
}


def canonical_report_snapshot(snapshot: Any) -> dict[str, Any]:
    """Validate and hash a bounded, source-free report snapshot."""
    if not isinstance(snapshot, dict):
        raise ValueError("report snapshot must be an object")
    _reject_prohibited(snapshot)
    value = deepcopy(snapshot)
    value.pop("source_hash", None)
    if value.get("schema_version") != 1:
        raise ValueError("report snapshot schema_version must be 1")
    for field in ("workspace_id", "work_package_id", "branch_id"):
        _safe_id(value.get(field), field=field)
    for field in (
        "title",
        "status",
        "graph_ref",
        "methodology_hash",
        "decision_contract_hash",
        "trial_plan_hash",
    ):
        _bounded_text(value.get(field), field=field)
    value["factor_family_versions"] = _text_refs(
        value.get("factor_family_versions"),
        field="factor_family_versions",
        allow_empty=False,
    )
    value["evidence_refs"] = _text_refs(
        value.get("evidence_refs"),
        field="evidence_refs",
    )
    value["sections"] = _canonical_sections(value.get("sections"))
    value["assets"] = _canonical_assets(value.get("assets"))
    value["gaps"] = _canonical_gaps(value.get("gaps"))
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise ValueError(
            f"report snapshot exceeds {MAX_SNAPSHOT_BYTES} bytes"
        )
    value["source_hash"] = hashlib.sha256(encoded).hexdigest()
    return value


def _canonical_sections(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > 32:
        raise ValueError("sections must contain between 1 and 32 items")
    sections = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("report section must be an object")
        section = {
            "section_id": item.get("section_id"),
            "title": item.get("title"),
            "body": item.get("body", ""),
            "evidence_refs": _text_refs(
                item.get("evidence_refs", []),
                field="section.evidence_refs",
            ),
            "asset_refs": _text_refs(
                item.get("asset_refs", []),
                field="section.asset_refs",
            ),
        }
        _safe_id(section["section_id"], field="section_id")
        _bounded_text(section["title"], field="section.title")
        _bounded_text(
            section["body"],
            field="section.body",
            allow_empty=True,
            maximum=4000,
        )
        sections.append(section)
    return sections


def _canonical_assets(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 32:
        raise ValueError("assets must be an array with at most 32 items")
    assets = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("report asset must be an object")
        asset = {
            field: item.get(field, "")
            for field in (
                "asset_ref",
                "content_hash",
                "media_type",
                "filename",
                "caption",
                "alt_text",
                "availability",
            )
        }
        asset["provenance_refs"] = _text_refs(
            item.get("provenance_refs", []),
            field="asset.provenance_refs",
        )
        for field, field_value in asset.items():
            if field != "provenance_refs":
                _bounded_text(
                    field_value,
                    field=f"asset.{field}",
                    allow_empty=field == "alt_text",
                )
        if not _SHA256.fullmatch(asset["content_hash"]):
            raise ValueError("asset.content_hash must be lowercase sha256")
        if Path(asset["filename"]).name != asset["filename"]:
            raise ValueError("asset.filename must not contain a path")
        if not asset["filename"].startswith(asset["content_hash"] + "."):
            raise ValueError("asset.filename must use its content hash")
        if asset["availability"] not in {
            "available",
            "missing",
            "unauthorized",
        }:
            raise ValueError("invalid asset availability")
        assets.append(asset)
    return assets


def _canonical_gaps(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 32:
        raise ValueError("gaps must be an array with at most 32 items")
    gaps = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("report gap must be an object")
        gap = {"gap_ref": item.get("gap_ref"), "reason": item.get("reason")}
        _bounded_text(gap["gap_ref"], field="gap_ref")
        _bounded_text(gap["reason"], field="gap.reason", maximum=1000)
        gaps.append(gap)
    return gaps


def _reject_prohibited(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in _PROHIBITED_KEYS:
                raise ValueError(f"prohibited report field: {key}")
            _reject_prohibited(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_prohibited(nested)


def _text_refs(
    value: Any,
    *,
    field: str,
    allow_empty: bool = True,
) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > 64
        or (not allow_empty and not value)
    ):
        raise ValueError(f"{field} must be a bounded string array")
    for item in value:
        _bounded_text(item, field=field)
    return list(value)


def _safe_id(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{field} must be a safe identifier")
    return value


def _bounded_text(
    value: Any,
    *,
    field: str,
    allow_empty: bool = False,
    maximum: int = 512,
) -> str:
    if (
        not isinstance(value, str)
        or (not allow_empty and not value.strip())
        or len(value.encode()) > maximum
    ):
        raise ValueError(f"{field} must be bounded text")
    return value
