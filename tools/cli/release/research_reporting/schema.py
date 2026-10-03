"""Bounded research report snapshot validation.

Only explicit report blocks are preserved. Source code and equations therefore
use the ``code`` and ``math`` block kinds rather than free-form fields.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import ntpath
from pathlib import Path
import posixpath
import re
from typing import Any
from urllib.parse import urlsplit

from .assets import canonical_asset_descriptor
from ..report_link_kinds import REPORT_LINK_KINDS

# These bounds cap disk and parsing cost without truncating ordinary long-running
# reports. Nothing at this boundary is sent to an Agent context.
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
MAX_REPORT_BYTES = 4 * 1024 * 1024
MAX_REPORT_SECTIONS = 4_096
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_LOCAL_PATH_IN_TEXT = re.compile(
    r'''(?:^|[\s"'`(\[=:])(?:~[/\\]|[A-Za-z]:[/\\]|/(?!/))'''
)
_RESULT_KINDS = {"ic", "factor_evaluation", "backtest", "robustness"}
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
    """Validate and hash a bounded report snapshot."""
    if not isinstance(snapshot, dict):
        raise ValueError("report snapshot must be an object")
    _reject_prohibited(snapshot)
    value = deepcopy(snapshot)
    value.pop("source_hash", None)
    if value.get("schema_version") != 1:
        raise ValueError("report snapshot schema_version must be 1")
    for field in ("workspace_id", "report_workspace_id", "branch_id"):
        _safe_id(value.get(field), field=field)
    for field in (
        "title",
        "status",
        "product_group",
        "methodology_hash",
        "decision_contract_hash",
    ):
        _bounded_text(value.get(field), field=field)
    _bounded_text(
        value.get("trial_plan_hash"),
        field="trial_plan_hash",
        allow_empty=True,
    )
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
    if (
        not isinstance(value, list)
        or not value
        or len(value) > MAX_REPORT_SECTIONS
    ):
        raise ValueError(
            f"sections must contain between 1 and {MAX_REPORT_SECTIONS} items"
        )
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
            "links": _canonical_links(item.get("links", [])),
            "created_at": item.get("created_at", 0.0),
        }
        _safe_id(section["section_id"], field="section_id")
        _bounded_text(section["title"], field="section.title")
        _bounded_text(
            section["body"],
            field="section.body",
            allow_empty=True,
            maximum=4000,
        )
        if (
            not isinstance(section["created_at"], (int, float))
            or not math.isfinite(section["created_at"])
            or section["created_at"] < 0
        ):
            raise ValueError("section.created_at must be a non-negative number")
        section["created_at"] = float(section["created_at"])
        if "blocks" in item:
            section["blocks"] = _canonical_blocks(
                item["blocks"],
                link_ids={link["link_id"] for link in section["links"]},
            )
        sections.append(section)
    return sections


def _canonical_blocks(
    value: Any,
    *,
    link_ids: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > 32:
        raise ValueError("section.blocks must be a bounded array")
    blocks = []
    used_link_ids: set[str] = set()
    for block in value:
        if not isinstance(block, dict):
            raise ValueError("section block must be an object")
        kind = block.get("kind")
        if kind == "math" and set(block) == {
            "kind", "latex", "fallback", "link_ids",
        }:
            refs = block["link_ids"]
            if (
                not isinstance(refs, list) or not refs or len(refs) > 16
                or any(ref not in link_ids for ref in refs)
            ):
                raise ValueError("section math links are invalid")
            blocks.append({
                "kind": kind,
                "latex": _bounded_text(
                    block["latex"], field="section.math.latex", maximum=2000,
                ),
                "fallback": _bounded_text(
                    block["fallback"],
                    field="section.math.fallback",
                    maximum=4000,
                ),
                "link_ids": list(refs),
            })
            used_link_ids.update(refs)
            continue
        if kind == "figure" and set(block) == {
            "kind", "asset", "link_ids",
        }:
            refs = block["link_ids"]
            if (
                not isinstance(refs, list) or not refs or len(refs) > 16
                or any(ref not in link_ids for ref in refs)
            ):
                raise ValueError("section figure links are invalid")
            blocks.append({
                "kind": kind,
                "asset": canonical_asset_descriptor(block["asset"]),
                "link_ids": list(refs),
            })
            used_link_ids.update(refs)
            continue
        if kind == "paragraph" and set(block) in (
            {"kind", "text"}, {"kind", "text", "link_ids"}
        ):
            projected = {
                "kind": kind,
                "text": _bounded_text(
                    block["text"], field="section.block.text", maximum=4000,
                ),
            }
            if "link_ids" in block:
                refs = block["link_ids"]
                if (
                    not isinstance(refs, list) or not refs
                    or len(refs) > 16
                    or any(ref not in link_ids for ref in refs)
                ):
                    raise ValueError("section paragraph links are invalid")
                projected["link_ids"] = list(refs)
                used_link_ids.update(refs)
            blocks.append(projected)
            continue
        if kind == "code" and set(block) in (
            {"kind", "language", "code"},
            {"kind", "language", "code", "link_ids"},
        ):
            projected = {
                "kind": kind,
                "language": _bounded_text(
                    block["language"], field="section.code.language",
                    maximum=64,
                ),
                "code": _bounded_text(
                    block["code"], field="section.code.code",
                    maximum=16000, allow_empty=True, reject_local_paths=False,
                ),
            }
            if "link_ids" in block:
                refs = block["link_ids"]
                if (
                    not isinstance(refs, list) or not refs
                    or len(refs) > 16
                    or any(ref not in link_ids for ref in refs)
                ):
                    raise ValueError("section code links are invalid")
                projected["link_ids"] = list(refs)
                used_link_ids.update(refs)
            blocks.append(projected)
            continue
        if kind == "list":
            expected = {"kind", "rows"}
        elif kind == "table":
            expected = {"kind", "columns", "rows"}
            if set(block) == expected | {"result_kind"}:
                result_kind = block["result_kind"]
                if result_kind not in _RESULT_KINDS:
                    raise ValueError("section table result_kind is invalid")
            elif set(block) == expected:
                result_kind = None
            else:
                raise ValueError("section block fields are invalid")
        else:
            expected = set()
        if kind not in {"list", "table"} or set(block) != expected and not (
            kind == "table" and set(block) == expected | {"result_kind"}
        ):
            raise ValueError("section block fields are invalid")
        columns = None
        if kind == "table":
            columns = block["columns"]
            if not isinstance(columns, list) or not 1 <= len(columns) <= 12:
                raise ValueError("section table columns are invalid")
            columns = [
                _bounded_text(item, field="section.table.column", maximum=128)
                for item in columns
            ]
        rows = block["rows"]
        if not isinstance(rows, list) or not rows or len(rows) > 64:
            raise ValueError("section block rows are invalid")
        projected_rows = []
        for row in rows:
            row_fields = (
                {"cells", "link_ids"}
                if columns is not None
                else {"text", "link_ids"}
            )
            if not isinstance(row, dict) or set(row) != row_fields:
                raise ValueError("section block row fields are invalid")
            refs = row["link_ids"]
            if (
                not isinstance(refs, list)
                or len(refs) > 16
                or any(ref not in link_ids for ref in refs)
            ):
                raise ValueError("section block row links are invalid")
            projected = {"link_ids": list(refs)}
            if columns is None:
                projected["text"] = _bounded_text(
                    row["text"], field="section.list.text", maximum=4000,
                )
            else:
                cells = row["cells"]
                if not isinstance(cells, list) or len(cells) != len(columns):
                    raise ValueError("section table row width is invalid")
                projected["cells"] = [
                    _bounded_text(
                        cell, field="section.table.cell", maximum=512,
                    )
                    for cell in cells
                ]
            projected_rows.append(projected)
        projected_block = {"kind": kind, "rows": projected_rows}
        if columns is not None:
            projected_block["columns"] = columns
        if kind == "table" and result_kind is not None:
            projected_block["result_kind"] = result_kind
        blocks.append(projected_block)
    return blocks


def _canonical_links(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 50:
        raise ValueError("section.links must contain at most 50 items")
    links = []
    seen_ids = set()
    for item in value:
        fields = set(item) if isinstance(item, dict) else set()
        if fields not in (
            {"link_id", "kind", "target_ref"},
            {"link_id", "kind", "target_ref", "label"},
        ):
            raise ValueError("section link fields are invalid")
        link_id = _bounded_text(item["link_id"], field="section.link_id")
        if link_id in seen_ids:
            raise ValueError("section.link_id must be unique")
        seen_ids.add(link_id)
        kind = item["kind"]
        if kind not in REPORT_LINK_KINDS:
            raise ValueError("section link kind is invalid")
        target_ref = _bounded_text(
            item["target_ref"],
            field="section.target_ref",
            reject_local_paths=False,
        )
        _stable_reference(target_ref, field="section.target_ref")
        link = {
            "link_id": link_id,
            "kind": kind,
            "target_ref": target_ref,
        }
        if "label" in item:
            link["label"] = _bounded_text(
                item["label"], field="section.link.label", maximum=160,
            )
        links.append(link)
    return links


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
                    reject_local_paths=field != "asset_ref",
                )
        _stable_reference(asset["asset_ref"], field="asset.asset_ref")
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
        _bounded_text(item, field=field, reject_local_paths=False)
        _stable_reference(item, field=field)
    return list(value)


def _stable_reference(value: str, *, field: str) -> str:
    parsed = urlsplit(value)
    network_reference = parsed.scheme.lower() in {"http", "https"}
    logical_absolute_path = (
        not parsed.netloc
        and (
            parsed.path.startswith(("/", "~"))
            or ntpath.isabs(parsed.path)
            or bool(ntpath.splitdrive(parsed.path)[0])
        )
    )
    if (
        parsed.scheme.lower() == "file"
        or (bool(parsed.netloc) and not network_reference)
        or (network_reference and not parsed.netloc)
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
        or logical_absolute_path
        or posixpath.isabs(value)
        or ntpath.isabs(value)
        or re.match(r"^[A-Za-z]:[\\/]", value)
        or value.startswith(("~/", "~\\", "./", ".\\", "../", "..\\"))
        or "\\" in value
        or re.search(r"(?:^|/)\.\.?($|/)", value)
        or ("/" in value and not _SCHEME.match(value))
    ):
        raise ValueError(f"{field} must be a stable reference")
    return value


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
    reject_local_paths: bool = True,
) -> str:
    if (
        not isinstance(value, str)
        or (not allow_empty and not value.strip())
        or len(value.encode()) > maximum
        or (reject_local_paths and _LOCAL_PATH_IN_TEXT.search(value))
    ):
        raise ValueError(f"{field} must be bounded text")
    return value
