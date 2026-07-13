"""Strategy-scope audit table helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from tools.cli.modules.backtest.audit_formatters import scope_tables


DisplayFieldValue = Callable[[str, Any], Any]
DisplayKey = Callable[[Any], str]
Normalize = Callable[[Any], Any]
ScalarCell = Callable[[Any], str]
LedgerScalarText = Callable[[Any], str | None]
ChangeCell = Callable[[Any, Any], str]
TableCellIsComplex = Callable[[Any], bool]

MISSING = object()


def is_strategy_entries(entries: Sequence[Mapping[str, Any]]) -> bool:
    return scope_tables.is_scoped_entries(
        entries,
        required_dimensions=("strategy",),
        allowed_record_scopes={"strategy_config", "strategy_context"},
    )


def strategy_table_cell(
    field_name: str,
    value: Any,
    *,
    display_field_value: DisplayFieldValue,
    table_cell_is_complex: TableCellIsComplex,
    scalar_cell: ScalarCell,
) -> Any:
    display_value = display_field_value(field_name, value)
    if table_cell_is_complex(display_value):
        return display_value
    return scalar_cell(display_value)


def scope_column_label(scope: str) -> str:
    if scope == "context":
        return "共享"
    if scope == "strategy_context":
        return "策略上下文"
    if scope == "strategy_config":
        return "策略配置"
    return scope or "value"


def scope_suffix(scope: str) -> str:
    if scope == "context":
        return "shared"
    if scope == "strategy_context":
        return "context"
    if scope == "strategy_config":
        return "config"
    return scope or "value"


def strategy_record_value_rows(
    field_name: str,
    values: Sequence[Mapping[str, Any]],
    *,
    display_field_value: DisplayFieldValue,
    display_key: DisplayKey,
    table_cell_is_complex: TableCellIsComplex,
    scalar_cell: ScalarCell,
) -> tuple[list[str], list[tuple[Any, ...]]] | None:
    if not values or any(str(entry.get("scope") or "") in {"ledger", "ledger_config"} for entry in values):
        return None
    strategy_entries = [
        entry for entry in values
        if str(entry.get("scope") or "") in {"strategy_config", "strategy_context"} and entry.get("strategy")
    ]
    if not strategy_entries:
        return None
    strategies = sorted(dict.fromkeys(scope_tables.scope_route(entry, ("strategy",))[0] for entry in strategy_entries))
    present_scopes = present_strategy_scopes(values)
    if not present_scopes:
        return None
    short_name = field_name.rsplit(".", 1)[-1]
    headers = [short_name] if len(present_scopes) == 1 else [scope_column_label(scope) for scope in present_scopes]
    shared_values = [entry.get("value") for entry in values if str(entry.get("scope") or "") == "context"]
    shared_value: Any = shared_values[-1] if shared_values else MISSING
    by_strategy_scope: dict[tuple[str, str], Any] = {}
    for entry in strategy_entries:
        by_strategy_scope[(scope_tables.scope_route(entry, ("strategy",))[0], str(entry.get("scope") or ""))] = entry.get("value")
    grouped: dict[tuple[str, ...], dict[str, Any]] = {}
    for strategy in strategies:
        row_values = []
        row_keys = []
        for scope in present_scopes:
            value = shared_value if scope == "context" else by_strategy_scope.get((strategy, scope), MISSING)
            display_value = "" if value is MISSING else strategy_table_cell(
                field_name,
                value,
                display_field_value=display_field_value,
                table_cell_is_complex=table_cell_is_complex,
                scalar_cell=scalar_cell,
            )
            row_values.append(display_value)
            row_keys.append(display_key(display_value))
        bucket = grouped.setdefault(tuple(row_keys), {"strategies": [], "values": row_values})
        bucket["strategies"].append(strategy)
    rows = [
        tuple([", ".join(bucket["strategies"]), *bucket["values"]])
        for bucket in grouped.values()
    ]
    return headers, rows


def strategy_scalar_record_table(
    record: Mapping[str, Any],
    *,
    display_field_value: DisplayFieldValue,
    display_key: DisplayKey,
    normalize: Normalize,
    scalar_cell: ScalarCell,
    table_cell_is_complex: TableCellIsComplex,
) -> tuple[list[str], dict[str, tuple[Any, ...]]] | None:
    field_name = str(record.get("field") or "")
    values = record.get("values") or []
    if not values or any(str(entry.get("scope") or "") in {"ledger", "ledger_config"} for entry in values):
        return None
    strategy_entries = [
        entry for entry in values
        if str(entry.get("scope") or "") in {"strategy_config", "strategy_context"} and entry.get("strategy")
    ]
    if not strategy_entries:
        return None
    present_scopes = present_strategy_scopes(values)
    if not present_scopes:
        return None
    short_name = field_name.rsplit(".", 1)[-1]
    shared_values = [entry.get("value") for entry in values if str(entry.get("scope") or "") == "context"]
    shared_value: Any = shared_values[-1] if shared_values else MISSING
    by_strategy_scope: dict[tuple[str, str], Any] = {}
    for entry in strategy_entries:
        key = (scope_tables.scope_route(entry, ("strategy",))[0], str(entry.get("scope") or ""))
        value = entry.get("value")
        if key in by_strategy_scope and display_key(by_strategy_scope[key]) != display_key(value):
            return None
        by_strategy_scope[key] = value
    strategies = sorted(dict.fromkeys(scope_tables.scope_route(entry, ("strategy",))[0] for entry in strategy_entries))
    scope_specs: list[tuple[str, list[str], bool]] = []
    for scope in present_scopes:
        base_column = short_name if len(present_scopes) == 1 else f"{short_name}.{scope_suffix(scope)}"
        candidate_values = [
            shared_value if scope == "context" else by_strategy_scope.get((strategy, scope), MISSING)
            for strategy in strategies
        ]
        expanded_columns = strategy_subfield_columns(short_name, base_column, candidate_values, normalize=normalize)
        if expanded_columns is None:
            scope_specs.append((scope, [base_column], False))
        else:
            scope_specs.append((scope, expanded_columns, True))
    columns = [column for _scope, scope_columns, _expanded in scope_specs for column in scope_columns]
    by_strategy: dict[str, tuple[Any, ...]] = {}
    for strategy in strategies:
        row_values: list[Any] = []
        for scope, scope_columns, expanded in scope_specs:
            value = shared_value if scope == "context" else by_strategy_scope.get((strategy, scope), MISSING)
            if value is MISSING:
                row_values.extend([""] * len(scope_columns))
            elif expanded:
                row_values.extend(strategy_subfield_values(value, len(scope_columns), normalize=normalize, scalar_cell=scalar_cell))
            else:
                row_values.append(strategy_table_cell(
                    field_name,
                    value,
                    display_field_value=display_field_value,
                    table_cell_is_complex=table_cell_is_complex,
                    scalar_cell=scalar_cell,
                ))
        by_strategy[strategy] = tuple(row_values)
    if not by_strategy:
        return None
    return columns, by_strategy


def strategy_scalar_change_record_table(
    field_name: str,
    changes: Sequence[Mapping[str, Any]],
    *,
    display_field_value: DisplayFieldValue,
    ledger_scalar_text: LedgerScalarText,
    change_cell: ChangeCell,
) -> tuple[list[str], dict[str, tuple[str, ...]]] | None:
    if not changes or any(str(change.get("scope") or "") in {"ledger", "ledger_config"} for change in changes):
        return None
    strategy_changes = [
        change for change in changes
        if str(change.get("scope") or "") in {"strategy_config", "strategy_context"} and change.get("strategy")
    ]
    if not strategy_changes:
        return None
    present_scopes = present_strategy_scopes(changes)
    if not present_scopes:
        return None
    short_name = field_name.rsplit(".", 1)[-1]
    columns = [short_name] if len(present_scopes) == 1 else [
        f"{short_name}.{scope_suffix(scope)}" for scope in present_scopes
    ]
    shared_changes = [change for change in changes if str(change.get("scope") or "") == "context"]
    shared_change: Mapping[str, Any] | None = shared_changes[-1] if shared_changes else None
    by_strategy_scope: dict[tuple[str, str], str] = {}
    for change in strategy_changes:
        before_text = ledger_scalar_text(display_field_value(field_name, change.get("before")))
        after_text = ledger_scalar_text(display_field_value(field_name, change.get("after")))
        if before_text is None or after_text is None:
            return None
        by_strategy_scope[(scope_tables.scope_route(change, ("strategy",))[0], str(change.get("scope") or ""))] = change_cell(before_text, after_text)
    shared_text = ""
    if shared_change is not None:
        before_text = ledger_scalar_text(display_field_value(field_name, shared_change.get("before")))
        after_text = ledger_scalar_text(display_field_value(field_name, shared_change.get("after")))
        if before_text is None or after_text is None:
            return None
        shared_text = change_cell(before_text, after_text)
    strategies = sorted(dict.fromkeys(scope_tables.scope_route(change, ("strategy",))[0] for change in strategy_changes))
    by_strategy: dict[str, tuple[str, ...]] = {}
    for strategy in strategies:
        row_values: list[str] = []
        for scope in present_scopes:
            row_values.append(shared_text if scope == "context" else by_strategy_scope.get((strategy, scope), ""))
        by_strategy[strategy] = tuple(row_values)
    return columns, by_strategy


def strategy_scalar_value_rows(
    field_name: str,
    values: Sequence[Mapping[str, Any]],
    *,
    display_field_value: DisplayFieldValue,
    ledger_scalar_text: LedgerScalarText,
) -> tuple[tuple[str, ...], list[tuple[Any, ...]]] | None:
    if not is_strategy_entries(values):
        return None
    grouped: dict[str, list[str]] = {}
    for entry in values:
        value_text = ledger_scalar_text(display_field_value(field_name, entry.get("value")))
        if value_text is None:
            return None
        grouped.setdefault(value_text, []).append(str(entry.get("strategy") or "?"))
    rows = [
        (", ".join(sorted(dict.fromkeys(strategies))), value_text)
        for value_text, strategies in grouped.items()
    ]
    return ("strategies", "value"), sorted(rows)


def strategy_scalar_change_rows(
    field_name: str,
    changes: Sequence[Mapping[str, Any]],
    *,
    display_field_value: DisplayFieldValue,
    ledger_scalar_text: LedgerScalarText,
    change_cell: ChangeCell,
) -> tuple[tuple[str, ...], list[tuple[Any, ...]]] | None:
    if not is_strategy_entries(changes):
        return None
    grouped: dict[tuple[str, str], list[str]] = {}
    for change in changes:
        before_text = ledger_scalar_text(display_field_value(field_name, change.get("before")))
        after_text = ledger_scalar_text(display_field_value(field_name, change.get("after")))
        if before_text is None or after_text is None:
            return None
        grouped.setdefault((before_text, after_text), []).append(str(change.get("strategy") or "?"))
    rows = [
        (", ".join(sorted(dict.fromkeys(strategies))), change_cell(before_text, after_text))
        for (before_text, after_text), strategies in grouped.items()
    ]
    return ("strategy", "change"), sorted(rows)


def combine_strategy_tables(
    tables: Sequence[tuple[Sequence[str], Mapping[str, tuple[Any, ...]]]],
    *,
    display_key: DisplayKey | None = None,
    annotate: Callable[[list[str], tuple[Any, ...]], tuple[Any, ...]] | None = None,
) -> tuple[list[str], list[tuple[Any, ...]]] | None:
    if not tables:
        return None
    strategy_keys = [tuple(sorted(table[1])) for table in tables]
    if not strategy_keys or any(keys != strategy_keys[0] for keys in strategy_keys[1:]):
        return None
    field_columns = [
        column
        for table in tables
        for column in table[0]
    ]
    value_maps = [table[1] for table in tables]
    grouped_rows: dict[tuple[Any, ...], dict[str, Any]] = {}
    for strategy in strategy_keys[0]:
        row_values = tuple(value for value_map in value_maps for value in value_map[strategy])
        if annotate is not None:
            row_values = annotate(field_columns, row_values)
        row_key = tuple(display_key(value) for value in row_values) if display_key is not None else row_values
        bucket = grouped_rows.setdefault(row_key, {"strategies": [], "values": row_values})
        bucket["strategies"].append(strategy)
    rows = [
        tuple([", ".join(bucket["strategies"]), *bucket["values"]])
        for bucket in grouped_rows.values()
    ]
    return field_columns, sorted(rows)


def annotated_strategy_row_values(field_columns: Sequence[str], row_values: tuple[Any, ...]) -> tuple[Any, ...]:
    values = list(row_values)
    by_column = {column: index for index, column in enumerate(field_columns)}
    warmup_mode_index = by_column.get("warmup_mode")
    warmup_window_index = by_column.get("warmup_window")
    if warmup_mode_index is not None and warmup_window_index is not None:
        mode = str(values[warmup_mode_index]).lower()
        if mode == "auto" and values[warmup_window_index] not in ("", "null", None):
            values[warmup_window_index] = f"{values[warmup_window_index]}（fixed模式配置；当前auto未生效）"
    signal_freq_index = by_column.get("signal_freq")
    required_frequency_index = (
        by_column["required_frequency.context"]
        if "required_frequency.context" in by_column
        else by_column.get("required_frequency")
    )
    if signal_freq_index is not None and required_frequency_index is not None:
        signal_value = values[signal_freq_index]
        required_value = values[required_frequency_index]
        if signal_value not in ("", "null", None) and required_value not in ("", "null", None):
            values[signal_freq_index] = f"{signal_value}（信号事件频率；因子/行情数据频率见required_frequency={required_value}）"
    return tuple(values)


def present_strategy_scopes(entries: Sequence[Mapping[str, Any]]) -> list[str]:
    scope_order = ["context", "strategy_context", "strategy_config"]
    return [
        scope for scope in scope_order
        if any(str(entry.get("scope") or "") == scope for entry in entries)
    ]


def strategy_subfield_columns(
    short_name: str,
    base_column: str,
    values: Sequence[Any],
    *,
    normalize: Normalize,
) -> list[str] | None:
    if short_name not in {"long_leg_strategy_ids", "short_leg_strategy_ids"}:
        return None
    return scope_tables.mapping_sequence_subfield_columns(
        base_column,
        [None if value is MISSING else value for value in values],
        normalize=normalize,
    )


def strategy_subfield_values(value: Any, expected_count: int, *, normalize: Normalize, scalar_cell: ScalarCell) -> list[str]:
    return scope_tables.mapping_sequence_subfield_values(
        value,
        expected_count,
        normalize=normalize,
        scalar_cell=scalar_cell,
    )


def single_mapping_sequence_keys(value: Any, *, normalize: Normalize) -> list[str] | None:
    return scope_tables.single_mapping_sequence_keys(value, normalize=normalize)


def single_mapping_sequence_item(value: Any, *, normalize: Normalize) -> dict[str, Any] | None:
    return scope_tables.single_mapping_sequence_item(value, normalize=normalize)
