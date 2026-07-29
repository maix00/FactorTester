"""Mask code markup while preserving report source coordinates."""

from __future__ import annotations

import re


_BACKTICKS = re.compile(r"(?<!\\)(`+)")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def mask_code_markup(value: str) -> str:
    masked = list(value)
    fenced = False
    fence_marker = ""
    offset = 0
    for line in value.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        fence = _FENCE.match(content)
        if fence:
            marker = fence.group(1)
            closing = (
                fenced
                and marker[0] == fence_marker[0]
                and len(marker) >= len(fence_marker)
                and not fence.group(2).strip()
            )
            if not fenced:
                fenced = True
                fence_marker = marker
            _blank(masked, offset, offset + len(content))
            if closing:
                fenced = False
                fence_marker = ""
            offset += len(line)
            continue
        if fenced:
            _blank(masked, offset, offset + len(content))
        else:
            _mask_inline(masked, content, offset)
        offset += len(line)
    return "".join(masked)


def _mask_inline(masked: list[str], line: str, base_offset: int) -> None:
    runs = list(_BACKTICKS.finditer(line))
    cursor = 0
    while cursor < len(runs):
        opening = runs[cursor]
        length = len(opening.group(1))
        closing = next(
            (
                index for index in range(cursor + 1, len(runs))
                if len(runs[index].group(1)) == length
            ),
            None,
        )
        if closing is None:
            return
        _blank(
            masked,
            base_offset + opening.start(),
            base_offset + runs[closing].end(),
        )
        cursor = closing + 1


def _blank(masked: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if masked[index] not in "\r\n":
            masked[index] = " "
