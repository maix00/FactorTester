"""Validation for the portable rich-text source stored in report node bodies.

The source is a deliberately small Markdown subset.  It keeps authored prose
easy for an agent to write while retaining typed report components for durable
assets, Job results, and other structured content.
"""

from __future__ import annotations

import json
import re


_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_HEADING = re.compile(r"^\s{0,3}#{1,6}(?:\s|$)")
_TABLE_DIVIDER = re.compile(r"^:?-{3,}:?$")
_TABLE_MAX_ROWS = 200
_TABLE_MAX_COLUMNS = 20
_TABLE_MAX_CELLS = 5_000


def validate_rich_text(value: str, *, field: str) -> str:
    """Require portable Markdown rich text rather than an opaque payload."""
    if not value.strip():
        return value
    _reject_json_payload(value, field=field)
    lines = value.splitlines()
    _validate_component_headings(lines, field=field)
    _validate_fences(lines, field=field)
    _validate_tables(lines, field=field)
    _validate_math_delimiters(value, field=field)
    return value


def _reject_json_payload(value: str, *, field: str) -> None:
    candidate = value.strip()
    if not candidate.startswith(("{", "[")):
        return
    try:
        json.loads(candidate)
    except json.JSONDecodeError:
        return
    raise ValueError(
        f"{field} is a JSON payload, not rich text; use a typed table, result, "
        "or special component"
    )


def _validate_component_headings(lines: list[str], *, field: str) -> None:
    if any(_HEADING.match(line) for line in lines):
        raise ValueError(
            f"{field} must use report chapter/section components, not Markdown headings"
        )


def _validate_fences(lines: list[str], *, field: str) -> None:
    opening = ""
    for line in lines:
        match = _FENCE.match(line)
        if match is None:
            continue
        marker = match.group(1)
        if not opening:
            opening = marker
        elif marker[0] == opening[0] and len(marker) >= len(opening):
            opening = ""
    if opening:
        raise ValueError(f"{field} has an unclosed fenced code block")


def _validate_tables(lines: list[str], *, field: str) -> None:
    index = 0
    while index + 1 < len(lines):
        columns = _table_cells(lines[index])
        divider = _table_cells(lines[index + 1])
        if not columns or len(columns) < 2 or len(columns) != len(divider):
            index += 1
            continue
        if not all(_TABLE_DIVIDER.fullmatch(cell) for cell in divider):
            index += 1
            continue
        if len(columns) > _TABLE_MAX_COLUMNS:
            raise ValueError(f"{field} has too many Markdown table columns")
        index += 2
        row_count = 0
        while index < len(lines):
            row = _table_cells(lines[index])
            if not row:
                break
            if len(row) != len(columns):
                raise ValueError(f"{field} has a Markdown table row with the wrong width")
            row_count += 1
            if row_count > _TABLE_MAX_ROWS or row_count * len(columns) > _TABLE_MAX_CELLS:
                raise ValueError(f"{field} exceeds the inline Markdown table limit")
            index += 1


def _table_cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if "|" not in stripped:
        return None
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    cells: list[str] = []
    current: list[str] = []
    code = False
    math: str | None = None
    index = 0
    while index < len(stripped):
        char = stripped[index]
        following = stripped[index + 1] if index + 1 < len(stripped) else ""
        if math is None and char == "`":
            code = not code
            current.append(char)
            index += 1
            continue
        if not code and char == "\\":
            pair = char + following
            if math is None and pair in {r"\(", r"\["}:
                math = pair
            elif math == r"\(" and pair == r"\)":
                math = None
            elif math == r"\[" and pair == r"\]":
                math = None
            current.append(pair)
            index += 2 if following else 1
            continue
        if not code and char == "$" and following == "$":
            math = None if math == "$$" else "$$"
            current.append("$$")
            index += 2
            continue
        if char == "|" and not code and math is None:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    cells.append("".join(current).strip())
    return cells


def _validate_math_delimiters(value: str, *, field: str) -> None:
    for opening, closing, label in (
        (r"\[", r"\]", "display LaTex"),
        (r"\(", r"\)", "inline LaTex"),
    ):
        if value.count(opening) != value.count(closing):
            raise ValueError(f"{field} has unmatched {label} delimiters")
    if value.count("$$") % 2:
        raise ValueError(f"{field} has unmatched display LaTex delimiters")
