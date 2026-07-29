"""Parse only the typed Markdown links an Agent explicitly authored."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .inline_links import (
    MARKDOWN_LABEL_PATTERN,
    decode_typed_url,
    unescape_markdown_label,
    validate_inline_links,
)


_MARKDOWN_LINK = re.compile(
    rf"(?<!\\)\[({MARKDOWN_LABEL_PATTERN})\]"
    r"\((factortester://[^\s()]+)\)"
)


@dataclass(frozen=True)
class DeclaredReportReference:
    kind: str
    target_ref: str
    label: str
    markdown_start: int = 0
    markdown_end: int = 0
    url_start: int = 0
    url_end: int = 0


def declared_inline_links(
    value: str, *, field: str,
) -> list[DeclaredReportReference]:
    """Return explicit links; never inspect surrounding prose for objects."""
    validate_inline_links(value, field=field)
    result: list[DeclaredReportReference] = []
    for match in _MARKDOWN_LINK.finditer(value):
        kind, target_ref = decode_typed_url(match.group(2), field=field)
        result.append(DeclaredReportReference(
            kind=kind,
            target_ref=target_ref,
            label=unescape_markdown_label(match.group(1)),
            markdown_start=match.start(),
            markdown_end=match.end(),
            url_start=match.start(2),
            url_end=match.end(2),
        ))
    return result
