"""Pure rich-text transforms used by the one-time report migration."""

from __future__ import annotations

import re
from pathlib import Path

from ..authoring.inline_links import (
    MARKDOWN_LINK_PATTERN,
    unescape_markdown_label,
)
from ..authoring.inline_code_policy import format_inline_code, format_inline_math


_MARKDOWN_LINK = re.compile(MARKDOWN_LINK_PATTERN)
_INLINE_CODE = re.compile(r"(?<!`)`[^`\n]+`(?!`)")
_WEB_URL = re.compile(r"https?://[^\s<>()\[\]，。；：、]+")
_LOCAL_FILE = re.compile(
    r"(?<![\w./-])"
    r"(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+"
    r"\.(?:md|markdown|csv|tsv|json|png|jpe?g|svg|pdf)"
    r"(?![\w./-])",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r".+?(?:[。！？；]|$)", re.DOTALL)
_BLOCK_MARKER = re.compile(
    r"(?m)^\s*(?:[-+*]\s+|\d+[.)]\s+|```|~~~|\||#{1,6}\s+|\$\$)"
)


def normalize_text(
    value: str, *, package_root: Path, listify: bool,
) -> tuple[str, list[str]]:
    """Format prose without inferring domain objects from its strings."""
    linked, linked_kinds = _link_references(value, package_root)
    if not listify or not _should_listify(linked):
        result, reasons = linked, linked_kinds
    else:
        items = [
            match.group(0).strip()
            for match in _SENTENCE.finditer(linked.strip())
            if match.group(0).strip()
        ]
        if len(items) < 2:
            result, reasons = linked, linked_kinds
        else:
            result = "\n".join(f"- {item}" for item in items)
            reasons = [*linked_kinds, "list"]
    result, math_tokens = format_inline_math(result)
    if math_tokens:
        reasons = [*reasons, "inline_math"]
    result, code_tokens = format_inline_code(result)
    if code_tokens:
        reasons = [*reasons, "inline_code"]
    if semantic_text(result) != semantic_text(value):
        raise ValueError("rich-text migration would change report semantics")
    return result, reasons


def semantic_text(value: str) -> str:
    """Remove only formatting introduced by this migration."""
    result = _MARKDOWN_LINK.sub(
        lambda match: unescape_markdown_label(match.group(1)), value,
    )
    result = re.sub(r"(?m)^\s*-\s+", "", result)
    result = re.sub(r"\\\((.*?)\\\)", r"\1", result)
    result = re.sub(r"(?<!`)`([^`\n]+)`(?!`)", r"\1", result)
    return re.sub(r"\s+", "", result)


def _link_references(
    value: str, package_root: Path,
) -> tuple[str, list[str]]:
    protected = [
        match.span()
        for pattern in (_MARKDOWN_LINK, _INLINE_CODE)
        for match in pattern.finditer(value)
    ]
    replacements: list[tuple[int, int, str, str]] = []
    for match in _WEB_URL.finditer(value):
        if _overlaps(match.span(), protected):
            continue
        replacements.append((
            match.start(), match.end(),
            f"[{match.group(0)}]({match.group(0)})", "url",
        ))
        protected.append(match.span())
    for match in _LOCAL_FILE.finditer(value):
        if _overlaps(match.span(), protected):
            continue
        candidate = match.group(0)
        if not _safe_existing_file(package_root, candidate):
            continue
        replacements.append((
            match.start(), match.end(),
            f"[{candidate}]({candidate})", "file",
        ))
        protected.append(match.span())
    result = value
    for start, end, replacement, _ in sorted(replacements, reverse=True):
        result = result[:start] + replacement + result[end:]
    reasons = [item[3] for item in sorted(replacements)]
    return result, list(dict.fromkeys(reasons))


def _safe_existing_file(package_root: Path, candidate: str) -> bool:
    root = package_root.resolve()
    target = (root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return target.is_file()


def _should_listify(value: str) -> bool:
    if len(value.strip()) < 120 or "\n\n" in value or _BLOCK_MARKER.search(value):
        return False
    return len([
        match.group(0) for match in _SENTENCE.finditer(value.strip())
        if match.group(0).strip()
    ]) >= 2


def _overlaps(
    span: tuple[int, int], protected: list[tuple[int, int]],
) -> bool:
    return any(span[0] < end and span[1] > start for start, end in protected)
