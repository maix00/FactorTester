"""Create the local report skeleton owned by one Profile Work Package."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .bindings import bindings_path_for, new_bindings
from .chapter_sync import ensure_report_chapters
from .model import document_hash, new_document
from .store import load_bindings, load_document, save_bindings, save_document


def ensure_profile_report_chapter(
    *,
    workspace_root: Path,
    work_package_id: str,
    title: str,
    node_id: str,
    branch_ref: str,
) -> dict[str, Any]:
    """Ensure the current Graph node has a local report chapter.

    This is deliberately a local operation.  A node entry is structural report
    state and does not require a server checkpoint or upload of report prose.
    Checkpoints and evidence are added later through the audit publisher.
    """
    package_root = Path(workspace_root).expanduser() / "research" / work_package_id
    report_path = package_root / "REPORT.json"
    if report_path.exists():
        document = load_document(report_path)
        bindings_path = bindings_path_for(report_path)
        bindings = load_bindings(bindings_path, document)
    else:
        document = new_document(
            f"report-{work_package_id}",
            title,
        )
        bindings = new_bindings(document)
        bindings_path = bindings_path_for(report_path)

    packet = {
        "node": {"node_id": node_id},
        "research_scope": {"branch_ref": branch_ref},
    }
    document, bindings, receipt = ensure_report_chapters(
        document, bindings, packet,
    )
    save_document(report_path, document)
    save_bindings(bindings_path, bindings, document)
    component_by_id = {
        item["component_id"]: item for item in document["components"]
    }
    section_refs = []
    for item in bindings["bindings"]:
        data = item.get("data") or {}
        if data.get("role") != "report_chapter":
            continue
        if data.get("branch_ref") not in {None, "", branch_ref}:
            continue
        component = component_by_id.get(item["component_id"])
        if component is None:
            continue
        section_refs.append({
            "link_id": item["binding_id"],
            "kind": "report_section",
            "target_ref": data["chapter_ref"],
            "section_ref": component["component_id"],
            "label": component["title"],
        })
    descriptor = {
        "artifact_ref": f"artifact:research/{work_package_id}/REPORT.json",
        "format": "document",
        "status": "ready",
        "content_hash": document_hash(document),
        "local_ref": report_path.as_uri(),
        "index_ref": "",
        "section_refs": section_refs,
    }
    return {
        "report_path": report_path,
        "bindings_path": bindings_path,
        "document": document,
        "bindings": bindings,
        "descriptor": descriptor,
        "chapter_sync": deepcopy(receipt),
    }
