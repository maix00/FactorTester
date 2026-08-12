"""Reject bare underscore identifiers in authored report prose."""

from __future__ import annotations

from dataclasses import dataclass
import re

from ..authoring.inline_links import MARKDOWN_LINK_PATTERN


_PROTECTED = re.compile(
    MARKDOWN_LINK_PATTERN
    + r"|\\\(.+?\\\)|\\\[.+?\\\]|\$\$.+?\$\$"
    + r"|https?://[^\s，。；：、]+",
    re.DOTALL,
)
_IDENTIFIER = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+"
    r"(?:\([A-Za-z0-9_., =+\-*/]*\))?"
    r"(?![A-Za-z0-9_])"
)


@dataclass(frozen=True)
class TechnicalIdentifierIssue:
    offset: int
    value: str


def unformatted_underscore_issues(value: str) -> list[TechnicalIdentifierIssue]:
    """Return visible underscore identifiers outside code, math, and links."""
    protected = [match.span() for match in _PROTECTED.finditer(value)]
    return [
        TechnicalIdentifierIssue(match.start(), match.group(0))
        for match in _IDENTIFIER.finditer(value)
        if not any(
            match.start() < right and match.end() > left
            for left, right in protected
        )
    ]
