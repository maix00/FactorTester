"""Locked, atomic projections for derived local research reports."""

from __future__ import annotations

import hashlib
import json
import math
import ntpath
import os
from pathlib import Path
import posixpath
import re
from typing import Any, Protocol
from urllib.parse import urlsplit

from .generation import publish_generation as _publish_generation
from .generation import work_package_lock as _work_package_lock
from .markdown import MarkdownReportTarget
from .schema import canonical_report_snapshot


MAX_INDEX_BYTES = 512 * 1024
MAX_INDEX_BRANCHES = 100
MAX_INDEX_SECTIONS = 100
MAX_INDEX_LINKS = 50
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_LOCAL_PATH_IN_TEXT = re.compile(
    r'''(?:^|[\s"'`(\[=:])(?:~[/\\]|[A-Za-z]:[/\\]|/(?!/))'''
)
_TOP_LEVEL_FIELDS = {
    "schema_version", "workspace_id", "work_package_id", "branches",
    "sections", "assets_ref", "omitted_section_count",
}
_BRANCH_FIELDS = {
    "branch_id", "title", "status", "source_hash", "content_hash",
    "report_ref", "media_type", "factor_family_versions", "evidence_refs",
    "asset_refs", "decision_contract_hash", "trial_plan_hash",
}
_SECTION_FIELDS = {
    "section_ref", "title", "summary", "links", "created_at",
}
_LINK_FIELDS = {"link_id", "kind", "target_ref", "section_ref"}
_LINK_KINDS = {"trial_plan", "obligation", "evidence", "report_section"}


class ReportTarget(Protocol):
    """Render one canonical snapshot without external I/O."""

    media_type: str
    extension: str

    def render(self, snapshot: dict[str, Any]) -> bytes:
        """Return deterministic report bytes."""
        ...


def render_branch_report(
    snapshot: dict[str, Any],
    *,
    workspace_root: Path,
    target: ReportTarget | None = None,
) -> dict[str, Any]:
    """Update one branch and its Work Package generation under one lock."""
    canonical = canonical_report_snapshot(snapshot)
    renderer = target or MarkdownReportTarget()
    branch_payload = renderer.render(canonical)
    package_root = (
        Path(workspace_root) / "research" / canonical["work_package_id"]
    )
    branch_path = (
        package_root / "branches" / canonical["branch_id"]
        / f"REPORT{renderer.extension}"
    )
    aggregate_path = package_root / "REPORT.md"
    index_path = package_root / "INDEX.json"
    assets_path = package_root / "assets"
    content_hash = hashlib.sha256(branch_payload).hexdigest()
    refs = _artifact_refs(canonical, renderer.extension)

    with _work_package_lock(package_root):
        index = _merge_index(
            _load_index(index_path, canonical),
            canonical,
            renderer,
            content_hash,
            refs,
        )
        index_payload = _encode_index(index)
        aggregate_payload = _render_work_package_report(index)
        assets_path.mkdir(parents=True, exist_ok=True)
        changed = _publish_generation([
            ("branch", branch_path, branch_payload),
            ("work_package_report", aggregate_path, aggregate_payload),
            ("index", index_path, index_payload),
        ])

    descriptor = _local_artifact_descriptor(
        refs=refs,
        branch_path=branch_path,
        index_path=index_path,
        content_hash=content_hash,
        branch_id=canonical["branch_id"],
        index=index,
    )
    return {
        "path": branch_path,
        "changed": any(changed.values()),
        "content_hash": content_hash,
        "source_hash": canonical["source_hash"],
        "branch_changed": changed["branch"],
        "index_changed": changed["index"],
        "work_package_report_changed": changed["work_package_report"],
        "index_path": index_path,
        "work_package_report_path": aggregate_path,
        "assets_path": assets_path,
        "artifact_refs": refs,
        "local_artifact_descriptor": descriptor,
    }


def _artifact_refs(
    snapshot: dict[str, Any],
    extension: str,
) -> dict[str, str]:
    root = f"artifact:research/{snapshot['work_package_id']}"
    return {
        "index": f"{root}/INDEX.json",
        "work_package_report": f"{root}/REPORT.md",
        "branch_report": (
            f"{root}/branches/{snapshot['branch_id']}/REPORT{extension}"
        ),
        "assets": f"{root}/assets/",
    }


def _load_index(
    path: Path,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": 1,
            "workspace_id": snapshot["workspace_id"],
            "work_package_id": snapshot["work_package_id"],
            "branches": [],
            "sections": [],
            "omitted_section_count": 0,
            "assets_ref": (
                f"artifact:research/{snapshot['work_package_id']}/assets/"
            ),
        }
    try:
        if path.stat().st_size > MAX_INDEX_BYTES:
            raise ValueError(
                f"Work Package report index exceeds {MAX_INDEX_BYTES} bytes"
            )
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Work Package report index is unreadable") from exc
    _validate_index(value, snapshot)
    return value


def _validate_index(value: Any, snapshot: dict[str, Any]) -> None:
    _exact_object(value, _TOP_LEVEL_FIELDS, "report index")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["workspace_id"] != snapshot["workspace_id"]
        or value["work_package_id"] != snapshot["work_package_id"]
    ):
        raise ValueError("Work Package report index identity is invalid")
    expected_assets = (
        f"artifact:research/{snapshot['work_package_id']}/assets/"
    )
    if value["assets_ref"] != expected_assets:
        raise ValueError("Work Package report assets_ref is invalid")
    if (
        type(value["omitted_section_count"]) is not int
        or value["omitted_section_count"] < 0
    ):
        raise ValueError("report index omitted_section_count is invalid")
    branches = _bounded_array(
        value["branches"], MAX_INDEX_BRANCHES, "report index branches"
    )
    branch_ids = set()
    for branch in branches:
        _validate_branch(branch, snapshot["work_package_id"])
        if branch["branch_id"] in branch_ids:
            raise ValueError("report index branch_id must be unique")
        branch_ids.add(branch["branch_id"])
    sections = _bounded_array(
        value["sections"], MAX_INDEX_SECTIONS, "report index sections"
    )
    section_refs = set()
    for section in sections:
        _validate_section(section, branch_ids)
        if section["section_ref"] in section_refs:
            raise ValueError("report index section_ref must be unique")
        section_refs.add(section["section_ref"])


def _validate_branch(value: Any, work_package_id: str) -> None:
    _exact_object(value, _BRANCH_FIELDS, "report index branch")
    branch_id = _safe_id(value["branch_id"], "branch_id")
    for field in ("title", "status", "media_type"):
        _bounded_text(value[field], field)
    for field in (
        "source_hash", "content_hash",
    ):
        if not isinstance(value[field], str) or not _SHA256.fullmatch(value[field]):
            raise ValueError(f"report index {field} must be lowercase sha256")
    for field in ("decision_contract_hash",):
        _bounded_text(value[field], field)
    _bounded_text(
        value["trial_plan_hash"],
        "trial_plan_hash",
        allow_empty=True,
    )
    expected_prefix = (
        f"artifact:research/{work_package_id}/branches/{branch_id}/REPORT."
    )
    report_ref = _reference(value["report_ref"], "report_ref")
    if not report_ref.startswith(expected_prefix):
        raise ValueError("report index report_ref is invalid")
    _reference_array(value["factor_family_versions"], 64, "factor versions")
    _reference_array(value["evidence_refs"], 64, "evidence refs")
    _reference_array(value["asset_refs"], 32, "asset refs")


def _validate_section(value: Any, branch_ids: set[str]) -> None:
    _exact_object(value, _SECTION_FIELDS, "report index section")
    section_ref = _bounded_text(value["section_ref"], "section_ref")
    if not any(
        section_ref.startswith(f"report-section:{branch_id}:")
        for branch_id in branch_ids
    ):
        raise ValueError("report index section_ref has no owning branch")
    _bounded_text(value["title"], "section title")
    _bounded_text(value["summary"], "section summary", allow_empty=True, maximum=4000)
    created_at = value["created_at"]
    if (
        not isinstance(created_at, (int, float))
        or not math.isfinite(created_at)
        or created_at < 0
    ):
        raise ValueError("report index section created_at is invalid")
    links = _bounded_array(value["links"], MAX_INDEX_LINKS, "section links")
    link_ids = set()
    for link in links:
        _exact_object(link, _LINK_FIELDS, "report index link")
        link_id = _bounded_text(link["link_id"], "link_id")
        if link_id in link_ids:
            raise ValueError("report index link_id must be unique per section")
        link_ids.add(link_id)
        if link["kind"] not in _LINK_KINDS:
            raise ValueError("report index link kind is invalid")
        _reference(link["target_ref"], "target_ref")
        if link["section_ref"] != section_ref:
            raise ValueError("report index link section_ref is invalid")


def _merge_index(
    index: dict[str, Any],
    snapshot: dict[str, Any],
    renderer: ReportTarget,
    content_hash: str,
    refs: dict[str, str],
) -> dict[str, Any]:
    value = dict(index)
    value["branches"] = sorted(
        [
            item for item in index["branches"]
            if item["branch_id"] != snapshot["branch_id"]
        ]
        + [_branch_entry(snapshot, renderer, content_hash, refs)],
        key=lambda item: item["branch_id"],
    )
    projected_sections = _project_sections(snapshot)
    projected_refs = {
        item["section_ref"] for item in projected_sections
    }
    merged_sections = sorted(
        [
            item for item in index["sections"]
            if item["section_ref"] not in projected_refs
        ]
        + projected_sections,
        key=lambda item: (item["created_at"], item["section_ref"]),
    )
    omitted_now = max(len(merged_sections) - MAX_INDEX_SECTIONS, 0)
    value["sections"] = (
        merged_sections[-MAX_INDEX_SECTIONS:]
        if omitted_now
        else merged_sections
    )
    value["omitted_section_count"] = (
        int(index["omitted_section_count"]) + omitted_now
    )
    _validate_index(value, snapshot)
    return value


def _encode_index(index: dict[str, Any]) -> bytes:
    payload = (
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if len(payload) > MAX_INDEX_BYTES:
        raise ValueError(
            f"Work Package report index exceeds {MAX_INDEX_BYTES} bytes"
        )
    return payload


def _branch_entry(
    snapshot: dict[str, Any],
    renderer: ReportTarget,
    content_hash: str,
    refs: dict[str, str],
) -> dict[str, Any]:
    return {
        "branch_id": snapshot["branch_id"],
        "title": snapshot["title"],
        "status": snapshot["status"],
        "source_hash": snapshot["source_hash"],
        "content_hash": content_hash,
        "report_ref": refs["branch_report"],
        "media_type": renderer.media_type,
        "factor_family_versions": snapshot["factor_family_versions"],
        "evidence_refs": snapshot["evidence_refs"],
        "asset_refs": [item["asset_ref"] for item in snapshot["assets"]],
        "decision_contract_hash": snapshot["decision_contract_hash"],
        "trial_plan_hash": snapshot["trial_plan_hash"],
    }


def _project_sections(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen = set()
    for section in snapshot["sections"]:
        section_ref = (
            f"report-section:{snapshot['branch_id']}:{section['section_id']}"
        )
        if section_ref in seen:
            raise ValueError("report section_id must be unique per branch")
        seen.add(section_ref)
        candidates = [
            {**link, "section_ref": section_ref}
            for link in section["links"]
        ]
        candidates.extend(
            {
                "link_id": (
                    f"{snapshot['branch_id']}:{section['section_id']}"
                    f":evidence:{index}"
                ),
                "kind": "evidence",
                "target_ref": target_ref,
                "section_ref": section_ref,
            }
            for index, target_ref in enumerate(section["evidence_refs"])
        )
        candidates.extend(
            {
                "link_id": (
                    f"{snapshot['branch_id']}:{section['section_id']}"
                    f":asset:{index}"
                ),
                "kind": "report_section",
                "target_ref": target_ref,
                "section_ref": section_ref,
            }
            for index, target_ref in enumerate(section["asset_refs"])
        )
        links = []
        seen_ids = set()
        seen_targets = set()
        for link in candidates:
            identity = (link["kind"], link["target_ref"])
            if identity in seen_targets:
                continue
            if link["link_id"] in seen_ids:
                raise ValueError("report link_id collision after projection")
            seen_ids.add(link["link_id"])
            seen_targets.add(identity)
            links.append(link)
        result.append({
            "section_ref": section_ref,
            "title": section["title"],
            "summary": section["body"][:1000],
            "links": links[:MAX_INDEX_LINKS],
            "created_at": section["created_at"],
        })
    return result


def _render_work_package_report(index: dict[str, Any]) -> bytes:
    lines = [
        f"# Work Package `{index['work_package_id']}`",
        "",
        f"- Workspace: `{index['workspace_id']}`",
        f"- Hypothesis branches: {len(index['branches'])}",
        f"- Omitted checkpoint sections: {index['omitted_section_count']}",
        "",
    ]
    for branch in index["branches"]:
        lines.extend([
            f"## {branch['title']}",
            "",
            f"- Branch: `{branch['branch_id']}`",
            f"- Status: `{branch['status']}`",
            f"- Source hash: `{branch['source_hash']}`",
            (
                f"- [Branch report](branches/{branch['branch_id']}"
                f"/REPORT{Path(branch['report_ref']).suffix})"
            ),
            "",
        ])
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _local_artifact_descriptor(
    *,
    refs: dict[str, str],
    branch_path: Path,
    index_path: Path,
    content_hash: str,
    branch_id: str,
    index: dict[str, Any],
) -> dict[str, Any]:
    return {
        "artifact_ref": refs["branch_report"],
        "format": "markdown",
        "status": "ready",
        "content_hash": content_hash,
        "local_ref": branch_path.resolve().as_uri(),
        "index_ref": index_path.resolve().as_uri(),
        "section_refs": [
            dict(link)
            for section in index["sections"]
            if section["section_ref"].startswith(
                f"report-section:{branch_id}:"
            )
            for link in section["links"]
        ],
    }


def _exact_object(value: Any, fields: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} fields are invalid")


def _bounded_array(value: Any, maximum: int, label: str) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{label} must be a bounded array")
    return value


def _reference_array(value: Any, maximum: int, label: str) -> list[str]:
    return [
        _reference(item, label)
        for item in _bounded_array(value, maximum, label)
    ]


def _safe_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ValueError(f"report index {field} must be a safe identifier")
    return value


def _bounded_text(
    value: Any,
    field: str,
    *,
    allow_empty: bool = False,
    maximum: int = 512,
    reject_local_paths: bool = True,
) -> str:
    if (
        not isinstance(value, str)
        or (not allow_empty and not value.strip())
        or len(value.encode("utf-8")) > maximum
        or (reject_local_paths and _LOCAL_PATH_IN_TEXT.search(value))
    ):
        raise ValueError(f"report index {field} must be bounded text")
    return value


def _reference(value: Any, field: str) -> str:
    result = _bounded_text(value, field, reject_local_paths=False)
    parsed = urlsplit(result)
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
        or posixpath.isabs(result)
        or ntpath.isabs(result)
        or re.match(r"^[A-Za-z]:[\\/]", result)
        or result.startswith(("~/", "~\\", "./", ".\\", "../", "..\\"))
        or "\\" in result
        or re.search(r"(?:^|/)\.\.?($|/)", result)
        or ("/" in result and not _SCHEME.match(result))
    ):
        raise ValueError(f"report index {field} must be a stable reference")
    return result
