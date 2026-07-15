"""Terminal table adapters backed by Rich."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from io import StringIO

from rich.cells import cell_len, set_cell_size
from rich.console import Console
from rich.table import Table
from rich.text import Text


def display_width(value: object) -> int:
    """Return terminal cell width using Rich's Unicode-aware implementation."""
    return cell_len(str(value))


def truncate_display(value: object, width: int) -> str:
    """Return a Rich-compatible ellipsized terminal cell."""
    text = str(value)
    if width <= 0 or display_width(text) <= width:
        return text
    rich_text = Text(text, no_wrap=True, overflow="ellipsis")
    truncated = rich_text.truncate(width, overflow="ellipsis")
    return (truncated or rich_text).plain


def pad_display(value: object, width: int, *, align: str = "left") -> str:
    """Pad one cell with Rich's Unicode-aware width handling."""
    text = str(value)
    if align == "right":
        return " " * max(width - cell_len(text), 0) + set_cell_size(text, width)
    return set_cell_size(text, width)


def render_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[object]],
    *,
    indent: str = "",
    aligns: Sequence[str] | None = None,
    max_widths: Sequence[int | None] | None = None,
) -> list[str]:
    """Render a plain terminal table through Rich, preserving the old API."""
    row_list = [tuple(row) for row in rows]
    if not row_list:
        return []

    aligns = tuple(aligns or ())
    max_widths = tuple(max_widths or ())
    table = Table(
        box=None,
        show_edge=False,
        pad_edge=False,
        padding=(0, 1),
        header_style="none",
    )
    for index, header in enumerate(headers):
        table.add_column(
            str(header),
            justify=aligns[index] if index < len(aligns) else "left",
            max_width=max_widths[index] if index < len(max_widths) else None,
            overflow="ellipsis",
            no_wrap=True,
        )
    for row in row_list:
        table.add_row(*(str(row[index]) if index < len(row) else "" for index in range(len(headers))))

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=240)
    console.print(table)
    return [indent + line.rstrip() for line in buffer.getvalue().splitlines()]


def render_key_value_rows(rows: Iterable[tuple[object, object]], *, indent: str = "") -> list[str]:
    """Render aligned ``field = value`` rows with Rich's borderless grid."""
    row_list = [(str(key), str(value)) for key, value in rows]
    if not row_list:
        return []

    table = Table.grid(padding=(0, 1))
    table.add_column(no_wrap=True)
    table.add_column(width=1, no_wrap=True)
    table.add_column(overflow="fold")
    for key, value in row_list:
        table.add_row(key, "=", value)

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=240)
    console.print(table)
    return [indent + line.rstrip() for line in buffer.getvalue().splitlines()]
