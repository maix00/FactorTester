"""Small terminal table helpers with East Asian display-width support."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import unicodedata


def display_width(value: object) -> int:
    text = str(value)
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
    return width


def truncate_display(value: object, width: int) -> str:
    text = str(value)
    if width <= 0 or display_width(text) <= width:
        return text
    if width <= 1:
        return "…"[:width]
    out = ""
    used = 0
    for char in text:
        char_width = 0 if unicodedata.combining(char) else (2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1)
        if used + char_width > width - 1:
            break
        out += char
        used += char_width
    return out + "…"


def pad_display(value: object, width: int, *, align: str = "left") -> str:
    text = str(value)
    missing = max(0, width - display_width(text))
    if align == "right":
        return " " * missing + text
    return text + " " * missing


def render_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[object]],
    *,
    indent: str = "",
    aligns: Sequence[str] | None = None,
    max_widths: Sequence[int | None] | None = None,
) -> list[str]:
    row_list = [tuple(row) for row in rows]
    if not row_list:
        return []
    col_count = len(headers)
    aligns = tuple(aligns or ())
    max_widths = tuple(max_widths or ())
    normalized_rows = [tuple(str(row[index]) if index < len(row) else "" for index in range(col_count)) for row in row_list]
    widths: list[int] = []
    for index, header in enumerate(headers):
        values = [header, *(row[index] for row in normalized_rows)]
        width = max(display_width(value) for value in values)
        cap = max_widths[index] if index < len(max_widths) else None
        if cap is not None:
            width = min(width, cap)
        widths.append(width)

    def _cell(value: object, index: int) -> str:
        align = aligns[index] if index < len(aligns) else "left"
        text = truncate_display(value, widths[index])
        return pad_display(text, widths[index], align=align)

    lines = [indent + "  ".join(_cell(header, index) for index, header in enumerate(headers))]
    for row in normalized_rows:
        lines.append(indent + "  ".join(_cell(value, index) for index, value in enumerate(row)))
    return lines
