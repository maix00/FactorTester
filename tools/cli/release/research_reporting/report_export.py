"""One export policy for a report document.

A downloaded report says what it is: the branch it was read from and the user
and profile that wrote that branch, then the export time and the version
numbers that describe the document.  The manager (server tree, client copy,
publication) and the CLI (native client export) all render the same front
matter through here, so an exported file is recognisable outside the platform.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .authoring.tree_render import render_report_markdown

MARKDOWN_CONTENT_TYPE = "text/markdown; charset=utf-8"


def principal_alias(principal: str) -> str:
    """Return the display alias of a principal reference.

    ``GTHT@MaxJJW@392452984564`` displays as ``MaxJJW``; anything else is
    already the display value.
    """
    text = str(principal or "").strip()
    parts = text.split("@")
    if len(parts) == 3 and parts[1] and parts[2].isdigit():
        return parts[1]
    return text


def export_timestamp(moment: datetime | None = None) -> str:
    """The moment the document was produced, with its offset."""
    return (moment or datetime.now().astimezone()).isoformat(timespec="seconds")


def document_identity(
    *,
    branch: str = "",
    owner: str = "",
    profile: str = "",
    generation: Any = 0,
    revision: str = "",
    projection_hash: str = "",
    report_id: str = "",
    exported_at: str = "",
) -> dict[str, Any]:
    """Collect the identity and version numbers of one exported report."""
    return {
        "branch": str(branch or "").strip(),
        "owner": str(owner or "").strip(),
        "profile": str(profile or "").strip(),
        "generation": int(generation or 0),
        "revision": str(revision or "").strip(),
        "projection_hash": str(projection_hash or "").strip(),
        "report_id": str(report_id or "").strip(),
        "exported_at": exported_at or export_timestamp(),
    }


def front_matter(identity: dict[str, Any] | None) -> list[str]:
    """Return the identity/version lines a downloaded report starts with."""
    value = identity or {}
    lines: list[str] = []
    if value.get("branch"):
        lines.append(f"- 分支：{value['branch']}")
    owner = str(value.get("owner") or "").strip()
    profile = str(value.get("profile") or "").strip()
    if owner and profile:
        lines.append(f"- 作者：{principal_alias(owner)}（profile: {profile}）")
    elif owner:
        lines.append(f"- 作者：{principal_alias(owner)}")
    elif profile:
        # A client profile that is not bound to an account yet still says which
        # profile the branch belongs to.
        lines.append(f"- 作者 profile：{profile}")
    if value.get("exported_at"):
        lines.append(f"- 导出时间：{value['exported_at']}")
    versions: list[str] = []
    if int(value.get("generation") or 0) > 0:
        versions.append(f"报告版本 {int(value['generation'])}")
    digest = str(value.get("projection_hash") or "").strip()
    revision = str(value.get("revision") or "").strip()
    # The branch revision and the published fingerprint are the same value for
    # a published branch; print it once.
    if revision and revision != digest:
        versions.append(f"分支版本 {revision[:12]}")
    if digest:
        versions.append(f"内容指纹 {digest[:12]}")
    if value.get("report_id"):
        versions.append(f"报告 ID {value['report_id']}")
    if versions:
        lines.append("- " + " · ".join(versions))
    return lines


def download_name(title: str) -> str:
    """Return a filesystem-safe stem for a report download."""
    safe = "".join(
        character for character in str(title or "") if character not in "/\\:"
    ).strip()
    return safe or "report"


def markdown_export(
    document: dict[str, Any],
    output_format: str = "md",
    *,
    identity: dict[str, Any] | None = None,
) -> tuple[bytes, str, str]:
    """Return ``(bytes, content_type, filename)`` for one report document.

    Only Markdown is produced here: the PDF renderer is a client binary, so a
    ``pdf`` request is refused and routed to the native export.
    """
    source_format = str(output_format or "md").strip().lower()
    if source_format not in {"md", "markdown"}:
        raise NotImplementedError("服务端仅支持导出 Markdown；PDF 请在客户端导出")
    title = str(
        document.get("title") or (document.get("head") or {}).get("title") or ""
    )
    payload = render_report_markdown(document, front_matter=front_matter(identity))
    return payload, MARKDOWN_CONTENT_TYPE, f"{download_name(title)}.md"


__all__ = [
    "MARKDOWN_CONTENT_TYPE",
    "document_identity",
    "download_name",
    "export_timestamp",
    "front_matter",
    "markdown_export",
    "principal_alias",
]
