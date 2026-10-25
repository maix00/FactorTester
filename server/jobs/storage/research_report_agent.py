"""Agent-readable views over a CouchDB Research Report document."""

from __future__ import annotations

import hashlib
import json
from typing import Any

REF_PREFIX = "research-report:"


def chapter_attachment_path(chapter_id: str) -> str:
    digest = hashlib.sha256(str(chapter_id).encode()).hexdigest()[:32]
    return f"chapters/{digest}.json"


def agent_manifest(document: dict[str, Any], projection: dict[str, Any]) -> dict[str, Any]:
    attachments = document.get("attachments") or {}
    chapters = []
    for item in projection.get("chapters") or []:
        chapter_id = str(item.get("component_id") or "")
        logical = chapter_attachment_path(chapter_id)
        meta = attachments.get(logical) or {}
        chapters.append({
            "chapter_id": chapter_id,
            "title": str(item.get("title") or ""),
            "preview": str(item.get("preview") or ""),
            "path": logical,
            "attachment": str(meta.get("name") or ""),
            "content_hash": str(meta.get("name") or "").removesuffix(".json"),
            "media_type": str(meta.get("content_type") or "application/json"),
        })
    return {
        "schema_version": 1,
        "kind": "research_report_agent_manifest",
        "report": {
            "id": str(document.get("_id") or ""),
            "publication_id": str(document.get("publication_id") or ""),
            "report_id": str(document.get("report_id") or ""),
            "owner_ref": str(document.get("owner_ref") or ""),
            "title": str(document.get("title") or ""),
            "visibility": str(document.get("visibility") or "private"),
            "projection_hash": str(document.get("projection_hash") or ""),
        },
        "chapters": chapters,
        "attachments": [
            {"path": path, **(meta or {})}
            for path, meta in sorted(attachments.items())
        ],
        "entrypoints": {
            "manifest": f"/api/research-reports/{document.get('publication_id')}/agent",
            "markdown": f"/api/research-reports/{document.get('publication_id')}/agent.md",
            "projection": f"/api/research-reports/{document.get('publication_id')}/projection",
        },
    }


def _component_markdown(component: dict[str, Any]) -> str:
    body = str(component.get("body") or "").strip()
    title = str(component.get("title") or "").strip()
    kind = str(component.get("kind") or "section")
    lines = [f"<!-- component:{component.get('component_id')} kind:{kind} -->"]
    if title and kind in {"chapter", "section", "heading"}:
        lines.append(f"## {title}")
    elif title:
        lines.extend([f"### {title}", ""])
    if body:
        lines.append(body)
    return "\n".join(lines).strip()


def agent_markdown(store, document: dict[str, Any], projection: dict[str, Any]) -> str:
    attachments = document.get("attachments") or {}
    lines = [f"# {document.get('title') or projection.get('title') or 'Research Report'}", ""]
    for chapter in projection.get("chapters") or []:
        chapter_id = str(chapter.get("component_id") or "")
        meta = attachments.get(chapter_attachment_path(chapter_id)) or {}
        name = str(meta.get("name") or "")
        if not name:
            continue
        raw = store.get_attachment(str(document.get("_id") or ""), name)
        chapter_doc = json.loads(raw)
        lines.extend([f"# {chapter_doc.get('title') or chapter.get('title') or ''}", ""])
        for component in chapter_doc.get("components") or []:
            value = _component_markdown(component)
            if value:
                lines.extend([value, ""])
    return "\n".join(lines).rstrip() + "\n"
