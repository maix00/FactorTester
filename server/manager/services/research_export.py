"""One download policy for every report channel.

A report is addressed by the same three channels the Web reader already uses:
a server-held tree (``server:``), the client's local copy (``local:``) and a
published projection (a bare publication id).  Each channel can describe its
report as the same document, so Markdown rendering, the PDF refusal and the
download name live here once instead of being repeated per route.
"""

from __future__ import annotations

from typing import Any

from tools.cli.release.research_reporting.authoring.tree_render import (
    render_report_markdown,
)

MARKDOWN_CONTENT_TYPE = "text/markdown; charset=utf-8"


def download_name(title: str) -> str:
    """Return a filesystem-safe stem for a report download."""
    safe = "".join(
        character for character in str(title or "") if character not in "/\\:"
    ).strip()
    return safe or "report"


def markdown_export(
    document: dict[str, Any], output_format: str = "md",
) -> tuple[bytes, str, str]:
    """Return ``(bytes, content_type, filename)`` for one report document.

    Only Markdown is produced server-side: the PDF renderer is a client binary,
    so a ``pdf`` request is refused here and routed to the native export.
    """
    source_format = str(output_format or "md").strip().lower()
    if source_format not in {"md", "markdown"}:
        raise NotImplementedError("服务端仅支持导出 Markdown；PDF 请在客户端导出")
    title = str(
        document.get("title") or (document.get("head") or {}).get("title") or ""
    )
    return (
        render_report_markdown(document),
        MARKDOWN_CONTENT_TYPE,
        f"{download_name(title)}.md",
    )


__all__ = ["MARKDOWN_CONTENT_TYPE", "download_name", "markdown_export"]
