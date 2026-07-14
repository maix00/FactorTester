"""Shared audit table rendering helpers for the backtest CLI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
import re
import shutil
import textwrap

import click

from tools.cli.table import display_width


TextFormatter = Callable[[Any], str]
DisplayKey = Callable[[Any], str]
Normalize = Callable[[Any], Any]
HighlightContent = Callable[[str], str]

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(value: object) -> str:
    return _ANSI_ESCAPE_RE.sub("", str(value))


def display_width_text(value: object) -> int:
    return display_width(strip_ansi(value))


def pad_cell(value: object, width: int) -> str:
    text = str(value)
    return text + " " * max(width - display_width_text(text), 0)


def max_width() -> int:
    return max(40, min(shutil.get_terminal_size((132, 20)).columns, 132))


def wrap_text(text: str, *, width: int, subsequent_indent: str = "") -> list[str]:
    if display_width_text(text) <= width:
        return [text]
    wrapped = textwrap.wrap(
        text,
        width=width,
        subsequent_indent=subsequent_indent,
        break_long_words=True,
        break_on_hyphens=False,
    )
    return wrapped or [text]


def table_lines(
    headers: tuple[str, ...] | list[str],
    rows: list[tuple[Any, ...]] | list[list[Any]],
    *,
    indent: str = "",
    allow_transpose: bool = True,
    allow_split: bool = True,
    text_formatter: TextFormatter,
    display_key: DisplayKey,
    normalize: Normalize,
    change_highlight_content: HighlightContent,
) -> list[str]:
    """Render audit tables without ellipsis and split complex cells into details."""
    if not rows:
        return []
    header_list = [str(header) for header in headers]
    scalar_rows: list[list[str]] = []
    details: list[tuple[int, str, Any]] = []
    detail_indexes: dict[tuple[str, str], int] = {}
    detail_index = 1
    for row in rows:
        scalar_row: list[str] = []
        for column_index, header in enumerate(header_list):
            cell = row[column_index] if column_index < len(row) else ""
            if table_cell_is_complex(cell):
                inline_text = inline_complex_cell_text(cell, text_formatter=text_formatter)
                if inline_text is not None:
                    scalar_row.append(inline_text)
                else:
                    detail_key = (str(header), display_key(normalize(cell)))
                    existing_index = detail_indexes.get(detail_key)
                    if existing_index is None:
                        existing_index = detail_index
                        detail_indexes[detail_key] = existing_index
                        details.append((existing_index, header, cell))
                        detail_index += 1
                    scalar_row.append(f"[明细 {existing_index}]")
            else:
                scalar_row.append(str(cell))
        scalar_rows.append(scalar_row)
    widths = [
        capped_column_width(
            header_list[column],
            max(
                display_width_text(header_list[column]),
                *(
                    max(display_width_text(part) for part in (row[column].splitlines() or [""]))
                    for row in scalar_rows
                ),
            ),
        )
        for column in range(len(header_list))
    ]
    transposed = (
        transposed_table_lines(
            header_list,
            scalar_rows,
            widths,
            indent=indent,
            change_highlight_content=change_highlight_content,
        )
        if allow_transpose
        else None
    )
    if transposed is not None:
        lines = transposed
        append_detail_lines(lines, details, indent=indent, text_formatter=text_formatter)
        return lines
    column_groups = (
        table_column_groups(header_list, scalar_rows, widths, indent=indent)
        if allow_split
        else [list(range(len(header_list)))]
    )
    if len(column_groups) > 1:
        lines: list[str] = []
        for group_index, columns in enumerate(column_groups, start=1):
            if lines:
                lines.append("")
            visible_headers = [header_list[column] for column in columns]
            non_key_headers = visible_headers[table_group_key_column_count(header_list, columns):]
            if non_key_headers:
                lines.append(f"{indent}columns {group_index}/{len(column_groups)}: {', '.join(non_key_headers)}")
            else:
                lines.append(f"{indent}columns {group_index}/{len(column_groups)}")
            lines.extend(table_block_lines(
                header_list,
                scalar_rows,
                widths,
                columns,
                indent=indent,
                change_highlight_content=change_highlight_content,
            ))
        append_detail_lines(lines, details, indent=indent, text_formatter=text_formatter)
        return lines
    lines = table_block_lines(
        header_list,
        scalar_rows,
        widths,
        column_groups[0],
        indent=indent,
        change_highlight_content=change_highlight_content,
    )
    append_detail_lines(lines, details, indent=indent, text_formatter=text_formatter)
    return lines


def inline_complex_cell_text(value: Any, *, text_formatter: TextFormatter) -> str | None:
    text = text_formatter(value)
    lines = text.splitlines() or [""]
    if len(lines) > 8:
        return None
    if any(display_width_text(line) > 72 for line in lines):
        return None
    return text


def append_detail_lines(
    lines: list[str],
    details: list[tuple[int, str, Any]],
    *,
    indent: str,
    text_formatter: TextFormatter,
) -> None:
    if not details:
        return
    separator = f"{indent}{'=' * 24}"
    lines.append(separator)
    for detail_offset, (index, header, value) in enumerate(details):
        if detail_offset:
            lines.append(separator)
        lines.append(f"{indent}明细 {index} ({header}):")
        for line in text_formatter(value).splitlines() or [""]:
            lines.append(f"{indent}  {line}")


def transposed_table_lines(
    header_list: list[str],
    scalar_rows: list[list[str]],
    widths: list[int],
    *,
    indent: str = "",
    change_highlight_content: HighlightContent,
) -> list[str] | None:
    if header_list and header_list[0] == "op":
        return None
    key_count = table_key_column_count(header_list)
    if header_list and header_list[0] in {"strategy", "strategies"} and len(scalar_rows) > 8:
        return None
    value_column_count = max(len(header_list) - 1, 0)
    should_transpose_dense = (
        key_count <= 2
        and len(header_list) >= 5
        and (
            (len(scalar_rows) <= 3 and value_column_count >= len(scalar_rows) + 3)
            or (len(header_list) > 16 and value_column_count > max(len(scalar_rows), 1))
        )
    )
    should_transpose_long_cell = (
        key_count <= 2
        and len(scalar_rows) <= 3
        and any(
            display_width_text(row[column]) > 48
            for row in scalar_rows
            for column in range(key_count, len(header_list))
        )
    )
    split_groups = table_column_groups(header_list, scalar_rows, widths, indent=indent)
    should_transpose_many_splits = (
        len(split_groups) >= 3
        and len(scalar_rows) <= 8
        and len(header_list) >= 5
    )
    if not (should_transpose_dense or should_transpose_long_cell or should_transpose_many_splits) and (len(header_list) <= 8 or len(scalar_rows) > 3):
        return None
    if key_count < 1 or key_count > 2:
        return None
    full_width = len(indent) + sum(widths) + max(len(widths) - 1, 0) * 2
    row_headers = [
        " | ".join(row[column] for column in range(key_count)).strip()
        for row in scalar_rows
    ]
    if full_width <= max_width() and not (should_transpose_dense or should_transpose_many_splits):
        return None
    key_detail_lines: list[str] = []
    if any(display_width_text(header) > 48 for header in row_headers):
        row_labels = [f"行{index}" for index in range(1, len(row_headers) + 1)]
        key_detail_rows = [
            tuple([row_labels[index], *[scalar_rows[index][column] for column in range(key_count)]])
            for index in range(len(scalar_rows))
        ]
        key_detail_lines = [f"{indent}行标明细:"]
        key_detail_lines.extend(table_lines(
            ("row", *header_list[:key_count]),
            key_detail_rows,
            indent=f"{indent}  ",
            text_formatter=str,
            display_key=str,
            normalize=lambda value: value,
            change_highlight_content=change_highlight_content,
        ))
        row_headers = row_labels
    transposed_rows = []
    for column in range(key_count, len(header_list)):
        values = [row[column] for row in scalar_rows]
        if len(values) > 1 and len(set(values)) == 1 and values[0] not in ("", "null"):
            transposed_rows.append(tuple([header_list[column], f"全部相同: {values[0]}", *[""] * (len(values) - 1)]))
        else:
            transposed_rows.append(tuple([header_list[column], *values]))
    transposed_headers = ["column", *row_headers]
    transposed_widths = [
        max(display_width_text(transposed_headers[column]), *(display_width_text(str(row[column])) for row in transposed_rows))
        for column in range(len(transposed_headers))
    ]
    key_label = " + ".join(header_list[:key_count])
    lines = [f"{indent}（表格已转置：原列数 {len(header_list)}，原行数 {len(scalar_rows)}，行标={key_label}）"]
    lines.extend(key_detail_lines)
    transposed_scalar_rows = [[str(item) for item in row] for row in transposed_rows]
    column_groups = table_column_groups(transposed_headers, transposed_scalar_rows, transposed_widths, indent=indent)
    for group_index, columns in enumerate(column_groups, start=1):
        if len(column_groups) > 1:
            if group_index > 1 or key_detail_lines:
                lines.append("")
            visible_headers = [transposed_headers[column] for column in columns]
            non_key_headers = visible_headers[table_group_key_column_count(transposed_headers, columns):]
            lines.append(f"{indent}columns {group_index}/{len(column_groups)}: {', '.join(non_key_headers)}")
        lines.extend(wrapped_table_block_lines(
            transposed_headers,
            transposed_scalar_rows,
            transposed_widths,
            columns,
            indent=indent,
            change_highlight_content=change_highlight_content,
        ))
    return lines


def table_block_lines(
    header_list: list[str],
    scalar_rows: list[list[str]],
    widths: list[int],
    columns: list[int],
    *,
    indent: str = "",
    change_highlight_content: HighlightContent | None = None,
) -> list[str]:
    lines = [
        indent + "  ".join(pad_cell(header_list[column], widths[column]) for column in columns).rstrip()
    ]
    for row in scalar_rows:
        cell_lines = [
            wrapped_table_cell(
                row[column],
                width=widths[column],
                max_lines=12,
                change_highlight_content=change_highlight_content,
            )
            for column in columns
        ]
        row_height = max(len(lines_for_cell) for lines_for_cell in cell_lines)
        for line_index in range(row_height):
            physical_cells = []
            for cell_index, column in enumerate(columns):
                parts = cell_lines[cell_index]
                physical_cells.append(pad_cell(parts[line_index] if line_index < len(parts) else "", widths[column]))
            lines.append(indent + "  ".join(physical_cells).rstrip())
    return lines


def capped_column_width(header: str, width: int) -> int:
    header_width = display_width_text(header)
    header_key = header.strip().lower()
    if header_key in {"products", "product", "instrument", "contract"}:
        return max(header_width, min(width, 56))
    if header_key in {"ledger", "cash pool", "ledgers", "cash pools"}:
        return max(header_width, min(width, 28))
    if header_key in {"strategies", "strategy"}:
        return max(header_width, min(width, 48))
    if header_key in {"order_id"}:
        return max(header_width, min(width, 48))
    return max(header_width, min(width, 72))


def wrapped_table_block_lines(
    header_list: list[str],
    scalar_rows: list[list[str]],
    widths: list[int],
    columns: list[int],
    *,
    indent: str = "",
    change_highlight_content: HighlightContent,
) -> list[str]:
    if len(columns) <= 1:
        return table_block_lines(
            header_list,
            scalar_rows,
            widths,
            columns,
            indent=indent,
            change_highlight_content=change_highlight_content,
        )
    available = max(18, max_width() - len(indent) - sum(widths[column] + 2 for column in columns[:-1]))
    lines = [
        indent + "  ".join(pad_cell(header_list[column], widths[column]) for column in columns).rstrip()
    ]
    for row in scalar_rows:
        wrapped_last = wrapped_table_cell(row[columns[-1]], width=available, change_highlight_content=change_highlight_content)
        first_line_cells = [
            pad_cell(row[column], widths[column])
            for column in columns[:-1]
        ]
        lines.append(indent + "  ".join([*first_line_cells, wrapped_last[0]]).rstrip())
        continuation_prefix = indent + "  ".join(" " * widths[column] for column in columns[:-1]) + "  "
        for continuation in wrapped_last[1:]:
            lines.append(continuation_prefix + continuation)
    return lines


def wrapped_table_cell(
    value: str,
    *,
    width: int,
    max_lines: int = 8,
    change_highlight_content: HighlightContent | None = None,
) -> list[str]:
    if not value:
        return [value]
    has_ansi_highlight = "\x1b[" in value
    has_change_highlight = has_ansi_highlight and " -> " in click.unstyle(value)
    wrap_value = click.unstyle(value) if has_ansi_highlight else value
    subsequent_indent = "  "
    wrapped: list[str] = []
    for physical_line in wrap_value.splitlines() or [""]:
        wrapped.extend(wrap_text(physical_line, width=width, subsequent_indent=subsequent_indent))
    if len(wrapped) <= max_lines:
        kept = wrapped
    else:
        kept = wrapped[: max_lines - 1]
        kept.append(f"{subsequent_indent}...（已截断 {len(wrapped) - len(kept)} 行）")
    if has_ansi_highlight and change_highlight_content is not None:
        return [change_highlight_content(line) for line in kept]
    return kept


def table_column_groups(
    header_list: list[str],
    scalar_rows: list[list[str]],
    widths: list[int],
    *,
    indent: str = "",
) -> list[list[int]]:
    if not header_list:
        return [[]]
    full_width = len(indent) + sum(widths) + max(len(widths) - 1, 0) * 2
    if full_width <= max_width():
        return [list(range(len(header_list)))]
    key_count = table_key_column_count(header_list)
    split_key_count = table_split_key_column_count(header_list, key_count)
    key_columns = list(range(min(split_key_count, len(header_list))))
    value_columns = list(range(min(key_count, len(header_list)), len(header_list)))
    if not value_columns:
        return [key_columns]
    key_width = sum(widths[column] for column in key_columns) + max(len(key_columns), 0) * 2
    available = max(20, max_width() - len(indent) - key_width)
    groups: list[list[int]] = []
    current: list[int] = []
    current_width = 0
    for column in value_columns:
        addition = widths[column] + (2 if current else 0)
        if current and current_width + addition > available:
            groups.append([*key_columns, *current])
            current = [column]
            current_width = widths[column]
        else:
            current.append(column)
            current_width += addition
    if current:
        groups.append([*key_columns, *current])
    return groups or [list(range(len(header_list)))]


def table_key_column_count(header_list: list[str]) -> int:
    if not header_list:
        return 0
    key_headers = {
        "key", "product", "strategy", "ledger", "cash pool", "notice_time",
        "timestamp", "index", "event", "order_id",
    }
    first = header_list[0]
    if first == "field" and len(header_list) > 1 and header_list[1] == "product":
        return 2
    if first in {"notice_time", "timestamp"} and len(header_list) > 1 and header_list[1] in {"strategy", "event"}:
        return 2
    if first == "ledger" and len(header_list) > 1 and header_list[1] == "cash pool":
        if len(header_list) > 3 and header_list[2] == "strategies" and header_list[3] in {"products", "product"}:
            return 4
        if len(header_list) > 2 and header_list[2] == "strategies":
            return 3
        return 2
    return 1 if first in key_headers else 1


def table_split_key_column_count(header_list: list[str], key_count: int | None = None) -> int:
    """Repeated index columns used only after a wide table is split.

    The unsplit table still shows the full semantic index.  Split tables repeat
    only the compact row identity so ledger/strategy totals do not waste every
    sub-table on cash-pool/strategy/product context columns.
    """
    if not header_list:
        return 0
    first = header_list[0]
    if first in {"ledger", "strategy", "strategies"}:
        return 1
    return key_count if key_count is not None else table_key_column_count(header_list)


def table_group_key_column_count(header_list: list[str], columns: list[int]) -> int:
    split_key_count = table_split_key_column_count(header_list)
    count = 0
    for expected_column in range(min(split_key_count, len(header_list))):
        if count < len(columns) and columns[count] == expected_column:
            count += 1
    return count


def table_cell_is_complex(value: Any) -> bool:
    if is_data_money_dict(value):
        return False
    return isinstance(value, (dict, list, tuple)) and not table_cell_is_scalar_sequence(value)


def is_data_money_dict(value: Any) -> bool:
    return isinstance(value, dict) and {"amount", "currency", "use_minor_units"} <= set(value)


def table_cell_is_scalar_sequence(value: Any) -> bool:
    if not isinstance(value, (list, tuple)):
        return False
    return len(value) <= 3 and all(not isinstance(item, (dict, list, tuple)) for item in value)
