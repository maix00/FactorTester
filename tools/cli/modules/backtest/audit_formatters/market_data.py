"""Market-data audit formatting helpers."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from tools.cli.modules.backtest.audit_formatters import table_render


TableRenderer = Callable[..., list[str]]
ScalarCell = Callable[[Any], str]
Normalize = Callable[[Any], Any]
DisplayValue = Callable[[str, Any], Any]
ChangeCell = Callable[[Any, Any], str]
SelectSamplePart = Callable[[dict[str, Any], Any], Any]
SampleNoteLines = Callable[[dict[str, Any], str], list[str]]
SingleSampleFrame = Callable[[dict[str, Any]], tuple[dict[str, Any], list[str]]]
SingleSampleSeries = Callable[[dict[str, Any]], tuple[dict[str, Any], list[str]]]


MARKET_DATA_SAMPLE_PRODUCT_LIMIT = 3
MARKET_SNAPSHOT_BASIS_ORDER = (
    "close",
    "open",
    "high",
    "low",
    "vwap",
    "settlement",
    "pre_settlement",
    "upper_limit",
    "lower_limit",
    "volume",
)
MARKET_SNAPSHOT_CONSTRAINT_COLUMNS = (
    "constraint_tradable",
    "can_buy",
    "can_sell",
    "reason",
    "limit_up_price",
    "limit_down_price",
)


def sample_rows_from_value_records(
    records: list[dict[str, Any]],
    *,
    display_field_value: DisplayValue,
    scalar_cell: ScalarCell,
    normalize: Normalize,
    select_sample_part: SelectSamplePart,
) -> tuple[list[tuple[Any, ...]], list[str]]:
    samples: list[tuple[str, str, dict[str, str]]] = []
    time_columns: list[str] = []
    for record in records:
        field_name = str(record.get("field") or "")
        for entry in record.get("values") or []:
            value = display_field_value(field_name, entry.get("value"))
            for field_label, product, values_by_time in sample_cells(
                field_name,
                value,
                scalar_cell=scalar_cell,
                normalize=normalize,
                select_sample_part=select_sample_part,
            ):
                samples.append((field_label, product, values_by_time))
                for time_label in values_by_time:
                    if time_label not in time_columns:
                        time_columns.append(time_label)
    return sample_rows(samples, time_columns), time_columns


def sample_rows_from_change_records(
    records: list[tuple[str, list[dict[str, Any]]]],
    *,
    display_field_value: DisplayValue,
    scalar_cell: ScalarCell,
    normalize: Normalize,
    change_cell: ChangeCell,
    select_sample_part: SelectSamplePart,
) -> tuple[list[tuple[Any, ...]], list[str]]:
    samples: list[tuple[str, str, dict[str, str]]] = []
    time_columns: list[str] = []
    for field_name, changes in records:
        for change in changes:
            before = display_field_value(field_name, change.get("before"))
            after = display_field_value(field_name, change.get("after"))
            before_cells = {
                (field_label, product): values_by_time
                for field_label, product, values_by_time in sample_cells(
                    field_name,
                    before,
                    scalar_cell=scalar_cell,
                    normalize=normalize,
                    select_sample_part=select_sample_part,
                )
            }
            for field_label, product, after_by_time in sample_cells(
                field_name,
                after,
                scalar_cell=scalar_cell,
                normalize=normalize,
                select_sample_part=select_sample_part,
            ):
                before_by_time = before_cells.get((field_label, product), {})
                changed_by_time = {
                    time_label: change_cell(before_by_time.get(time_label, "null"), after_value)
                    for time_label, after_value in after_by_time.items()
                }
                samples.append((field_label, product, changed_by_time))
                for time_label in changed_by_time:
                    if time_label not in time_columns:
                        time_columns.append(time_label)
    return sample_rows(samples, time_columns), time_columns


def snapshot_rows_from_value_records(
    records: list[dict[str, Any]],
    *,
    display_field_value: DisplayValue,
    scalar_cell: ScalarCell,
    normalize: Normalize,
) -> tuple[tuple[str, ...], list[tuple[Any, ...]]] | None:
    values: dict[str, Any] = {}
    for record in records:
        field_name = str(record.get("field") or "")
        short_name = field_name.rsplit(".", 1)[-1]
        for entry in record.get("values") or []:
            candidate = display_field_value(field_name, entry.get("value"))
            if short_name not in values or snapshot_value_present(candidate, normalize=normalize):
                values[short_name] = candidate
    return snapshot_rows(values, scalar_cell=scalar_cell, normalize=normalize)


def snapshot_rows_from_change_records(
    records: list[tuple[str, list[dict[str, Any]]]],
    *,
    display_field_value: DisplayValue,
    scalar_cell: ScalarCell,
    normalize: Normalize,
    change_cell: ChangeCell,
) -> tuple[tuple[str, ...], list[tuple[Any, ...]]] | None:
    before_values: dict[str, Any] = {}
    after_values: dict[str, Any] = {}
    for field_name, changes in records:
        short_name = field_name.rsplit(".", 1)[-1]
        for change in changes:
            before_candidate = display_field_value(field_name, change.get("before"))
            after_candidate = display_field_value(field_name, change.get("after"))
            if short_name not in before_values or snapshot_value_present(before_candidate, normalize=normalize):
                before_values[short_name] = before_candidate
            if short_name not in after_values or snapshot_value_present(after_candidate, normalize=normalize):
                after_values[short_name] = after_candidate
    return snapshot_change_rows(
        before_values,
        after_values,
        scalar_cell=scalar_cell,
        normalize=normalize,
        change_cell=change_cell,
    )


def snapshot_rows(
    values: Mapping[str, Any],
    *,
    scalar_cell: ScalarCell,
    normalize: Normalize,
) -> tuple[tuple[str, ...], list[tuple[Any, ...]]] | None:
    parsed = snapshot_components(values, normalize=normalize)
    products = snapshot_products(parsed)
    if not products:
        return None
    basis_columns = snapshot_basis_columns(parsed["current_market_snapshot"])
    historical_field_columns = snapshot_historical_field_columns(parsed["current_historical_fields"])
    headers = snapshot_headers(parsed, basis_columns, historical_field_columns)
    rows = [
        snapshot_row(
            product,
            parsed,
            basis_columns,
            historical_field_columns,
            scalar_cell=scalar_cell,
            missing="",
            include_selected_price=bool(parsed.get("current_prices")),
            include_tradable_status=bool(parsed.get("current_tradable_status")),
            include_constraints=bool(parsed.get("current_order_constraints")),
            include_historical_fields=bool(parsed.get("current_historical_fields")),
        )
        for product in products
    ]
    return headers, rows


def snapshot_change_rows(
    before_values: Mapping[str, Any],
    after_values: Mapping[str, Any],
    *,
    scalar_cell: ScalarCell,
    normalize: Normalize,
    change_cell: ChangeCell,
) -> tuple[tuple[str, ...], list[tuple[Any, ...]]] | None:
    before = snapshot_components(before_values, normalize=normalize)
    after = snapshot_components(after_values, normalize=normalize)
    products = sorted(
        set(snapshot_products(before)) | set(snapshot_products(after)),
        key=str,
    )
    if not products:
        return None
    basis_columns = snapshot_basis_columns({
        **before["current_market_snapshot"],
        **after["current_market_snapshot"],
    })
    union = snapshot_union_components(before, after)
    historical_field_columns = snapshot_historical_field_columns(union["current_historical_fields"])
    headers = snapshot_headers(union, basis_columns, historical_field_columns)
    include_selected_price = bool(union.get("current_prices"))
    include_tradable_status = bool(union.get("current_tradable_status"))
    include_constraints = bool(union.get("current_order_constraints"))
    include_historical_fields = bool(union.get("current_historical_fields"))
    rows = []
    for product in products:
        before_row = snapshot_row(
            product,
            before,
            basis_columns,
            historical_field_columns,
            scalar_cell=scalar_cell,
            missing="null",
            include_selected_price=include_selected_price,
            include_tradable_status=include_tradable_status,
            include_constraints=include_constraints,
            include_historical_fields=include_historical_fields,
        )
        after_row = snapshot_row(
            product,
            after,
            basis_columns,
            historical_field_columns,
            scalar_cell=scalar_cell,
            missing="null",
            include_selected_price=include_selected_price,
            include_tradable_status=include_tradable_status,
            include_constraints=include_constraints,
            include_historical_fields=include_historical_fields,
        )
        rows.append(tuple([
            str(product),
            *[
                change_cell(before_cell, after_cell)
                for before_cell, after_cell in zip(before_row[1:], after_row[1:], strict=False)
            ],
        ]))
    return headers, rows


def snapshot_components(values: Mapping[str, Any], *, normalize: Normalize) -> dict[str, Any]:
    return {
        "current_market_snapshot": snapshot_mapping(values.get("current_market_snapshot"), normalize=normalize),
        "current_prices": flat_mapping(values.get("current_prices"), normalize=normalize),
        "current_tradable_status": flat_mapping(values.get("current_tradable_status"), normalize=normalize),
        "current_order_constraints": constraint_mapping(values.get("current_order_constraints"), normalize=normalize),
        "current_historical_fields": historical_field_mapping(values.get("current_historical_fields"), normalize=normalize),
    }


def snapshot_value_present(value: Any, *, normalize: Normalize) -> bool:
    normalized = normalize(value)
    if normalized in (None, "", (), []):
        return False
    if isinstance(normalized, Mapping) and not normalized:
        return False
    return True


def snapshot_union_components(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: {
            **(before.get(key) or {}),
            **(after.get(key) or {}),
        }
        if isinstance(before.get(key), Mapping) or isinstance(after.get(key), Mapping)
        else after.get(key) or before.get(key)
        for key in (
            "current_market_snapshot",
            "current_prices",
            "current_tradable_status",
            "current_order_constraints",
            "current_historical_fields",
        )
    }


def snapshot_mapping(value: Any, *, normalize: Normalize) -> dict[str, dict[str, Any]]:
    normalized = normalize(value)
    if not isinstance(normalized, Mapping):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for basis, basis_values in normalized.items():
        if not isinstance(basis_values, Mapping):
            continue
        out[str(basis)] = {str(product): item for product, item in basis_values.items()}
    return out


def flat_mapping(value: Any, *, normalize: Normalize) -> dict[str, Any]:
    normalized = normalize(value)
    if not isinstance(normalized, Mapping):
        return {}
    return {str(product): item for product, item in normalized.items()}


def constraint_mapping(value: Any, *, normalize: Normalize) -> dict[str, dict[str, Any]]:
    normalized = normalize(value)
    if not isinstance(normalized, Mapping):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for product, constraint in normalized.items():
        item = constraint_item(constraint, normalize=normalize)
        if item:
            out[str(product)] = item
    return out


def historical_field_mapping(value: Any, *, normalize: Normalize) -> dict[str, dict[str, Any]]:
    normalized = normalize(value)
    if not isinstance(normalized, Mapping):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for product, fields in normalized.items():
        if not isinstance(fields, Mapping):
            continue
        item = {
            str(field): field_value
            for field, field_value in fields.items()
            if not isinstance(field_value, (Mapping, list, tuple))
        }
        if item:
            out[str(product)] = item
    return out


def constraint_item(value: Any, *, normalize: Normalize) -> dict[str, Any]:
    normalized = normalize(value)
    if isinstance(normalized, Mapping):
        return {str(key): item for key, item in normalized.items()}
    result: dict[str, Any] = {}
    for attr in ("tradable", "can_buy", "can_sell", "reason", "limit_up_price", "limit_down_price"):
        if hasattr(value, attr):
            result[attr] = getattr(value, attr)
    return result


def snapshot_products(parsed: Mapping[str, Any]) -> list[str]:
    products: set[str] = set()
    snapshot = parsed.get("current_market_snapshot") or {}
    if isinstance(snapshot, Mapping):
        for basis_values in snapshot.values():
            if isinstance(basis_values, Mapping):
                products.update(str(product) for product in basis_values)
    for key in ("current_prices", "current_tradable_status", "current_order_constraints", "current_historical_fields"):
        values = parsed.get(key) or {}
        if isinstance(values, Mapping):
            products.update(str(product) for product in values)
    return sorted(products, key=str)


def snapshot_basis_columns(snapshot: Mapping[str, Mapping[str, Any]]) -> list[str]:
    available = {str(basis) for basis, values in snapshot.items() if isinstance(values, Mapping) and values}
    ordered = [basis for basis in MARKET_SNAPSHOT_BASIS_ORDER if basis in available]
    ordered.extend(sorted(available - set(ordered)))
    return ordered


def snapshot_historical_field_columns(historical_fields: Mapping[str, Mapping[str, Any]]) -> list[str]:
    columns: list[str] = []
    for fields in historical_fields.values():
        if not isinstance(fields, Mapping):
            continue
        for field_name in fields:
            field = str(field_name)
            if field not in columns:
                columns.append(field)
    return columns


def snapshot_headers(
    parsed: Mapping[str, Any],
    basis_columns: Sequence[str],
    historical_field_columns: Sequence[str],
) -> tuple[str, ...]:
    headers: list[str] = ["product", *basis_columns]
    if parsed.get("current_prices"):
        headers.append("selected_price")
    if parsed.get("current_tradable_status"):
        headers.append("tradable_status")
    if parsed.get("current_order_constraints"):
        headers.extend(MARKET_SNAPSHOT_CONSTRAINT_COLUMNS)
    if parsed.get("current_historical_fields"):
        headers.extend(historical_field_columns)
    return tuple(headers)


def snapshot_row(
    product: str,
    parsed: Mapping[str, Any],
    basis_columns: Sequence[str],
    historical_field_columns: Sequence[str],
    *,
    scalar_cell: ScalarCell,
    missing: str,
    include_selected_price: bool,
    include_tradable_status: bool,
    include_constraints: bool,
    include_historical_fields: bool,
) -> tuple[Any, ...]:
    snapshot = parsed.get("current_market_snapshot") or {}
    prices = parsed.get("current_prices") or {}
    tradable_status = parsed.get("current_tradable_status") or {}
    constraints = parsed.get("current_order_constraints") or {}
    historical_fields = parsed.get("current_historical_fields") or {}
    constraint = constraints.get(product, {}) if isinstance(constraints, Mapping) else {}
    product_fields = historical_fields.get(product, {}) if isinstance(historical_fields, Mapping) else {}
    row: list[Any] = [
        str(product),
        *[
            snapshot_value(snapshot, basis, product, scalar_cell=scalar_cell, missing=missing)
            for basis in basis_columns
        ],
    ]
    if include_selected_price:
        row.append(mapping_value(prices, product, scalar_cell=scalar_cell, missing=missing))
    if include_tradable_status:
        row.append(mapping_value(tradable_status, product, scalar_cell=scalar_cell, missing=missing))
    if include_constraints:
        row.extend(
            constraint_value(constraint, column, scalar_cell=scalar_cell, missing=missing)
            for column in MARKET_SNAPSHOT_CONSTRAINT_COLUMNS
        )
    if include_historical_fields:
        row.extend(
            constraint_value(product_fields, column, scalar_cell=scalar_cell, missing=missing)
            for column in historical_field_columns
        )
    return tuple(row)


def snapshot_value(
    snapshot: Any,
    basis: str,
    product: str,
    *,
    scalar_cell: ScalarCell,
    missing: str,
) -> str:
    if not isinstance(snapshot, Mapping):
        return missing
    basis_values = snapshot.get(basis)
    if not isinstance(basis_values, Mapping):
        return missing
    return mapping_value(basis_values, product, scalar_cell=scalar_cell, missing=missing)


def mapping_value(mapping: Any, product: str, *, scalar_cell: ScalarCell, missing: str) -> str:
    if not isinstance(mapping, Mapping) or product not in mapping:
        return missing
    return scalar_cell(mapping.get(product))


def constraint_value(constraint: Any, column: str, *, scalar_cell: ScalarCell, missing: str) -> str:
    if not isinstance(constraint, Mapping):
        return missing
    source_column = "tradable" if column == "constraint_tradable" else column
    if source_column not in constraint:
        return missing
    return scalar_cell(constraint.get(source_column))


def sample_rows(samples: list[tuple[str, str, dict[str, str]]], time_columns: list[str]) -> list[tuple[Any, ...]]:
    return [
        tuple([field_label, product, *[values_by_time.get(time_label, "") for time_label in time_columns]])
        for field_label, product, values_by_time in samples
    ]


def sample_cells(
    field_name: str,
    value: Any,
    *,
    scalar_cell: ScalarCell,
    normalize: Normalize,
    select_sample_part: SelectSamplePart,
) -> list[tuple[str, str, dict[str, str]]]:
    normalized = normalize(value)
    if not isinstance(normalized, Mapping):
        return []
    short_name = field_name.rsplit(".", 1)[-1]
    if normalized.get("type") == "PriceTablesSummary":
        return price_tables_sample_cells(
            dict(normalized),
            scalar_cell=scalar_cell,
            normalize=normalize,
            select_sample_part=select_sample_part,
        )
    if normalized.get("type") == "DataFrame":
        return frame_sample_cells(
            short_name,
            dict(normalized),
            scalar_cell=scalar_cell,
            normalize=normalize,
        )
    if normalized.get("type") == "Series":
        return series_sample_cells(
            short_name,
            dict(normalized),
            scalar_cell=scalar_cell,
            select_sample_part=select_sample_part,
        )
    if normalized and all(not isinstance(item, (dict, list, tuple)) for item in normalized.values()):
        return [
            (short_name, str(product), {"value": scalar_cell(scalar_value)})
            for product, scalar_value in list(sorted(normalized.items()))[:MARKET_DATA_SAMPLE_PRODUCT_LIMIT]
        ]
    return []


def price_tables_sample_cells(
    value: dict[str, Any],
    *,
    scalar_cell: ScalarCell,
    normalize: Normalize,
    select_sample_part: SelectSamplePart,
) -> list[tuple[str, str, dict[str, str]]]:
    rows = value.get("rows")
    if not isinstance(rows, list):
        return []
    cells: list[tuple[str, str, dict[str, str]]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        basis = str(row.get("basis") or "")
        cells.extend(frame_sample_cells(
            f"price_tables.{basis}",
            row,
            scalar_cell=scalar_cell,
            normalize=normalize,
        ))
    return cells


def frame_sample_cells(
    field_label: str,
    value: dict[str, Any],
    *,
    scalar_cell: ScalarCell,
    normalize: Normalize,
) -> list[tuple[str, str, dict[str, str]]]:
    sample = value.get("sample")
    frames = price_sample_edge_frames(sample, normalize=normalize) if isinstance(sample, dict) else [("value", value)]
    if not frames:
        return []
    selected_products: list[str] = []
    per_product: dict[str, dict[str, str]] = {}
    for _sample_name, part in frames:
        columns = [str(column) for column in (part.get("columns") or [])]
        if not selected_products:
            selected_products = columns[:MARKET_DATA_SAMPLE_PRODUCT_LIMIT]
        indexes = part.get("index")
        rows = part.get("rows")
        if not isinstance(indexes, list) or not isinstance(rows, list):
            continue
        for index_item, row_values in zip(indexes, rows, strict=False):
            if not isinstance(row_values, list):
                continue
            time_label = sample_time_label(index_parts(index_item))
            for column_index, product in enumerate(columns):
                if product not in selected_products or column_index >= len(row_values):
                    continue
                per_product.setdefault(product, {})[time_label] = scalar_cell(row_values[column_index])
    return [(field_label, product, per_product.get(product, {})) for product in selected_products if per_product.get(product)]


def series_sample_cells(
    field_label: str,
    value: dict[str, Any],
    *,
    scalar_cell: ScalarCell,
    select_sample_part: SelectSamplePart,
) -> list[tuple[str, str, dict[str, str]]]:
    sample = value.get("sample")
    if isinstance(sample, dict):
        selected = select_sample_part(sample, lambda part: isinstance(part, dict))
        value = selected.value if selected is not None else value
    indexes = value.get("index")
    values = value.get("values")
    if not isinstance(indexes, list) or not isinstance(values, list):
        return []
    return [
        (field_label, index_cell(product), {"value": scalar_cell(scalar_value)})
        for product, scalar_value in list(zip(indexes, values, strict=False))[:MARKET_DATA_SAMPLE_PRODUCT_LIMIT]
    ]


def price_tables_text(
    value: Mapping[str, Any],
    *,
    table_lines: TableRenderer,
    scalar_cell: ScalarCell,
    normalize: Normalize,
) -> str:
    rows = value.get("rows")
    if not isinstance(rows, list):
        return "price_tables: (no rows)"
    sample_rows: list[tuple[Any, ...]] = []
    sample_columns: list[str] = []
    lines: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        basis = str(row.get("basis") or "")
        sample = row.get("sample")
        if isinstance(sample, dict):
            selected_frames = price_sample_edge_frames(sample, normalize=normalize)
            if selected_frames:
                for _sample_name, part in selected_frames:
                    part_columns = [str(column) for column in (part.get("columns") or [])]
                    for column in part_columns:
                        if column not in sample_columns:
                            sample_columns.append(column)
                    for index_item, row_values in zip(part.get("index") or [], part.get("rows") or [], strict=False):
                        value_map = {
                            str(column): scalar_cell(row_values[index])
                            for index, column in enumerate(part_columns)
                            if index < len(row_values)
                        }
                        sample_rows.append((
                            basis,
                            _sample_name,
                            index_parts(index_item),
                            value_map,
                        ))
    if sample_rows and sample_columns:
        sample_times: list[str] = []
        grouped_values: dict[tuple[str, str], dict[str, str]] = {}
        for basis, _sample_name, sample_index, value_map in sample_rows:
            sample_time = sample_time_label(sample_index)
            if sample_time not in sample_times:
                sample_times.append(sample_time)
            for column in sample_columns:
                grouped_values.setdefault((basis, column), {})[sample_time] = value_map.get(column, "")
        lines.append("价格字段 sample（行索引=field/product，列=首尾 sample 时间）:")
        rendered_rows = [
            tuple([basis, product, *[values.get(sample_time, "") for sample_time in sample_times]])
            for (basis, product), values in sorted(grouped_values.items())
        ]
        lines.extend(table_lines(
            ("field", "product", *sample_times),
            rendered_rows,
            indent="  ",
            allow_transpose=False,
            allow_split=False,
        ))
    return "\n".join(lines) if lines else "price_tables: (no sample)"


def market_data_load_plan_text(
    value: Mapping[str, Any],
    *,
    table_lines: TableRenderer,
) -> str:
    items = value.get("items")
    if isinstance(items, Mapping):
        table_rows = [
            (
                str(product),
                details.get("frequency") or "",
                details.get("data_source") or "",
            )
            for product, details in sorted(items.items())
            if isinstance(details, Mapping)
        ]
    else:
        rows = value.get("rows")
        if not isinstance(rows, list):
            return "market_data_load_plan: (no rows)"
        table_rows = [
            (
                row.get("product") or "",
                row.get("frequency") or "",
                row.get("data_source") or "",
            )
            for row in rows
            if isinstance(row, Mapping)
        ]
    lines = [f"planned products = {value.get('count', len(table_rows))}"]
    if table_rows:
        lines.extend(table_lines(("product", "frequency", "data_source"), table_rows, indent="  ", allow_transpose=False))
    return "\n".join(lines)


def market_data_excluded_products_text(
    value: Mapping[str, Any],
    *,
    scalar_sequence_text: Callable[..., str],
) -> str:
    rows = value.get("rows")
    if not isinstance(rows, list):
        return "excluded_out_of_range_products: (no rows)"
    products = [str(row.get("product") or "") for row in rows if isinstance(row, Mapping) and row.get("product")]
    if not products:
        return "excluded products = 0"
    return "\n".join([
        f"excluded products = {value.get('count', len(products))}",
        scalar_sequence_text(products, width=96),
    ])


def dataframe_text(
    value: Mapping[str, Any],
    *,
    table_lines: TableRenderer,
    select_sample_part: SelectSamplePart,
    sample_note_lines: SampleNoteLines,
    single_sample_frame: SingleSampleFrame,
) -> str:
    lines: list[str] = []
    shape = value.get("shape")
    if isinstance(shape, list | tuple) and len(shape) == 2:
        header = f"pd.DataFrame shape=({shape[0]}, {shape[1]})"
    else:
        rows = value.get("rows")
        columns = value.get("columns")
        row_count = len(rows) if isinstance(rows, list) else "?"
        column_count = len(columns) if isinstance(columns, list) else "?"
        header = f"pd.DataFrame shape=({row_count}, {column_count})"
    lines.append(header)
    index_bounds = value.get("index")
    if isinstance(index_bounds, Mapping) and {"start", "end"} <= set(index_bounds):
        lines.append(f"index.start = {index_bounds.get('start')}")
        lines.append(f"index.end   = {index_bounds.get('end')}")
    if value.get("truncated"):
        lines.append("truncated   = True")
    columns = value.get("columns")
    if value.get("truncated"):
        if isinstance(columns, list):
            lines.append(f"columns     = {json.dumps(columns, ensure_ascii=False, default=str)}")
        elif isinstance(columns, Mapping):
            summary = columns_summary(columns)
            if summary:
                lines.append(f"columns     = {summary}")

    sample = value.get("sample")
    if isinstance(sample, dict):
        selected = select_sample_part(sample, lambda part: isinstance(part, dict))
        if selected is not None:
            lines.extend(sample_note_lines(sample, selected.name))
            part, row_notes = single_sample_frame(selected.value)
            lines.extend(row_notes)
            lines.append(f"sample.{selected.name}:")
            lines.extend(dataframe_table_lines(part, table_lines=table_lines, indent="  "))
    else:
        lines.extend(dataframe_table_lines(value, table_lines=table_lines, indent="  "))
    return "\n".join(lines)


def pandas_text(
    value: Any,
    *,
    dataframe_formatter: Callable[[dict[str, Any]], str],
    series_formatter: Callable[[dict[str, Any]], str],
) -> str | None:
    if not isinstance(value, dict):
        return None
    value_type = value.get("type")
    if value_type == "DataFrame":
        return dataframe_formatter(value)
    if value_type == "Series":
        return series_formatter(value)
    return None


def dataframe_table_lines(
    value: Mapping[str, Any],
    *,
    table_lines: TableRenderer,
    indent: str = "",
) -> list[str]:
    columns = [str(column) for column in value.get("columns", [])]
    indexes = value.get("index", [])
    rows = value.get("rows", [])
    if not isinstance(indexes, list) or not isinstance(rows, list):
        return [f"{indent}(no tabular rows)"]
    table_rows = []
    for index, row in zip(indexes, rows, strict=False):
        row_values = row if isinstance(row, list) else [row]
        table_rows.append((str(index), *[str(item) for item in row_values]))
    if not table_rows:
        return [f"{indent}(empty)"]
    return table_lines(("index", *columns), table_rows, indent=indent)


def series_text(
    value: Mapping[str, Any],
    *,
    table_lines: TableRenderer,
    select_sample_part: SelectSamplePart,
    sample_note_lines: SampleNoteLines,
    single_sample_series: SingleSampleSeries,
) -> str:
    name = value.get("name")
    length = value.get("length")
    if length is not None:
        header = f"pd.Series name={name!r} length={length}"
    else:
        values = value.get("values")
        header = f"pd.Series name={name!r} length={len(values) if isinstance(values, list) else '?'}"
    index_bounds = value.get("index")
    if isinstance(index_bounds, Mapping) and {"start", "end"} <= set(index_bounds):
        header = f"{header} index={index_bounds.get('start')} → {index_bounds.get('end')}"
    if value.get("truncated"):
        header = f"{header} truncated=True"

    lines = [header]
    sample = value.get("sample")
    if isinstance(sample, dict):
        selected = select_sample_part(sample, lambda part: isinstance(part, dict))
        if selected is not None:
            lines.extend(sample_note_lines(sample, selected.name))
            part, row_notes = single_sample_series(selected.value)
            lines.extend(row_notes)
            lines.append(f"sample.{selected.name}:")
            lines.extend(series_table_lines(part, table_lines=table_lines, indent="  "))
    else:
        lines.extend(series_table_lines(value, table_lines=table_lines, indent="  "))
    return "\n".join(lines)


def series_table_lines(
    value: Mapping[str, Any],
    *,
    table_lines: TableRenderer,
    indent: str = "",
) -> list[str]:
    indexes = value.get("index", [])
    values = value.get("values", [])
    if not isinstance(indexes, list) or not isinstance(values, list):
        return [f"{indent}(no series rows)"]
    table_rows = [(str(index), str(item)) for index, item in zip(indexes, values, strict=False)]
    if not table_rows:
        return [f"{indent}(empty)"]
    return table_lines(("index", "value"), table_rows, indent=indent)


def index_cell(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return " | ".join(str(item) for item in value)
    return str(value)


def price_sample_edge_frames(
    sample: Mapping[str, Any],
    *,
    normalize: Normalize,
) -> list[tuple[str, dict[str, Any]]]:
    frames: list[tuple[str, dict[str, Any]]] = []
    seen_indexes: set[str] = set()
    for name, row_selector in (("head", 0), ("tail", -1)):
        frame = sample.get(name)
        if not isinstance(frame, dict):
            continue
        indexes = frame.get("index")
        rows = frame.get("rows")
        if not isinstance(indexes, list) or not isinstance(rows, list) or not indexes or not rows:
            continue
        selected_index = indexes[row_selector]
        selected_row = rows[row_selector]
        index_key = json.dumps(normalize(selected_index), ensure_ascii=False, sort_keys=True, default=str)
        if index_key in seen_indexes:
            continue
        seen_indexes.add(index_key)
        frames.append((
            name,
            {
                **frame,
                "index": [selected_index],
                "rows": [selected_row],
            },
        ))
    return frames


def index_parts(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value or "")]


def sample_time_label(parts: Sequence[str]) -> str:
    if len(parts) >= 2:
        return f"{parts[0]} | {parts[1]}"
    return parts[0] if parts else ""


def columns_summary(columns: Any) -> str:
    if isinstance(columns, Mapping):
        count = columns.get("count")
        sampled = columns.get("sampled")
        sampled_count = len(sampled) if isinstance(sampled, list) else 0
        if count is not None and sampled_count:
            return f"{count} columns; sample shows {sampled_count} columns"
        if count is not None:
            return f"{count} columns"
    if isinstance(columns, list):
        if len(columns) <= 20:
            return json.dumps(columns, ensure_ascii=False, default=str)
        return f"{len(columns)} columns"
    return str(columns or "")


HISTORICAL_FIELD_STATE_HINTS = {
    "VolumeMultiple",
    "OpenRatioByMoney",
    "OpenRatioByVolume",
    "CloseRatioByMoney",
    "CloseRatioByVolume",
    "CloseTodayRatioByMoney",
    "CloseTodayRatioByVolume",
    "LongMarginRatioByMoney",
    "ShortMarginRatioByMoney",
    "LongMarginRatioByVolume",
    "ShortMarginRatioByVolume",
    "CostBasisMethod",
    "MoneyCalculationPolicy",
}


def historical_field_state_summary(
    value: Any,
    *,
    normalize: Normalize,
    product_filter: Sequence[str] = (),
) -> dict[str, Any] | None:
    normalized = normalize(value)
    if not isinstance(normalized, Mapping) or not normalized:
        return None
    rows: list[dict[str, Any]] = []
    field_names: list[str] = []
    for product, fields in normalized.items():
        if not isinstance(fields, Mapping):
            return None
        row: dict[str, Any] = {"product": str(product)}
        for field_name, field_value in fields.items():
            field_name_text = str(field_name)
            if isinstance(field_value, (dict, list, tuple)):
                return None
            if field_name_text not in field_names:
                field_names.append(field_name_text)
            row[field_name_text] = field_value
        rows.append(row)
    if not rows or not field_names:
        return None
    if product_filter:
        filter_set = set(product_filter)
        filtered_rows = [row for row in rows if str(row.get("product") or "") in filter_set]
        if filtered_rows:
            rows = filtered_rows
            present_products = {str(row.get("product") or "") for row in rows}
            return {
                "type": "HistoricalFieldStateTable",
                "fields": field_names,
                "rows": rows,
                "product_filter": tuple(product for product in product_filter if product in present_products),
            }
    return {"type": "HistoricalFieldStateTable", "fields": field_names, "rows": rows}


def is_historical_field_state_summary(value: Mapping[str, Any]) -> bool:
    fields = {str(field) for field in (value.get("fields") or [])}
    return bool(fields & HISTORICAL_FIELD_STATE_HINTS)


def historical_field_state_text(
    value: Mapping[str, Any],
    *,
    table_lines: TableRenderer,
    scalar_cell: ScalarCell,
) -> str:
    fields = [str(field) for field in (value.get("fields") or [])]
    rows = value.get("rows")
    if not fields or not isinstance(rows, list):
        return "historical field state: (no rows)"
    field_rows = [row for row in rows if isinstance(row, dict)]
    if not field_rows:
        return "historical field state: (empty)"
    product_filter = tuple(str(item) for item in (value.get("product_filter") or ()))
    return "\n".join(field_state_transposed_lines(
        fields,
        field_rows,
        product_filter=product_filter,
        table_lines=table_lines,
        scalar_cell=scalar_cell,
    ))


def historical_field_state_diff_text(
    before: Any,
    after: Any,
    *,
    table_lines: TableRenderer,
    scalar_cell: ScalarCell,
    change_cell: ChangeCell,
) -> str | None:
    if not (
        isinstance(before, Mapping)
        and isinstance(after, Mapping)
        and before.get("type") == "HistoricalFieldStateTable"
        and after.get("type") == "HistoricalFieldStateTable"
    ):
        return None
    fields = list(dict.fromkeys([str(field) for field in (before.get("fields") or []) + (after.get("fields") or [])]))
    before_rows = {
        str(row.get("product") or ""): row
        for row in before.get("rows") or []
        if isinstance(row, Mapping)
    }
    after_rows = {
        str(row.get("product") or ""): row
        for row in after.get("rows") or []
        if isinstance(row, Mapping)
    }
    table_rows: list[dict[str, Any]] = []
    for product in sorted(set(before_rows) | set(after_rows)):
        before_row = before_rows.get(product, {})
        after_row = after_rows.get(product, {})
        changed_row: dict[str, Any] = {"product": product}
        row_changed = False
        for field in fields:
            before_value = before_row.get(field)
            after_value = after_row.get(field)
            if before_value != after_value:
                changed_row[field] = change_cell(scalar_cell(before_value), scalar_cell(after_value))
                row_changed = True
            else:
                changed_row[field] = ""
        if row_changed:
            table_rows.append(changed_row)
    if not table_rows:
        return "（无变化）"
    product_filter = tuple(str(item) for item in (after.get("product_filter") or before.get("product_filter") or ()))
    return "\n".join(field_state_transposed_lines(
        fields,
        table_rows,
        product_filter=product_filter,
        table_lines=table_lines,
        scalar_cell=scalar_cell,
    ))


def field_state_transposed_lines(
    fields: list[str],
    rows: list[dict[str, Any]],
    *,
    product_filter: Sequence[str] = (),
    table_lines: TableRenderer,
    scalar_cell: ScalarCell,
) -> list[str]:
    if product_filter:
        sampled_rows = sorted(rows, key=lambda row: str(row.get("product") or ""))
        note = f"event products: {', '.join(product_filter)}"
    else:
        sampled_rows, note = sample_field_state_products(rows)
    products = [str(row.get("product") or "") for row in sampled_rows]
    table_rows = []
    for field in fields:
        values = [scalar_cell(row.get(field)) for row in sampled_rows]
        if any(value not in ("", "null") for value in values):
            table_rows.append(tuple([field, *values]))
    lines: list[str] = []
    if note:
        lines.extend(table_render.wrap_text(note, width=table_render.max_width(), subsequent_indent="  "))
    if table_rows:
        lines.extend(table_lines(("field", *products), table_rows, allow_transpose=False))
    return lines or ["（无字段值）"]


def sample_field_state_products(rows: list[dict[str, Any]], *, max_products: int = 6) -> tuple[list[dict[str, Any]], str | None]:
    sorted_rows = sorted(rows, key=lambda row: str(row.get("product") or ""))
    if len(sorted_rows) <= max_products:
        return sorted_rows, None
    head_count = max_products // 2
    tail_count = max_products - head_count
    sampled = [*sorted_rows[:head_count], *sorted_rows[-tail_count:]]
    products = ", ".join(str(row.get("product") or "") for row in sampled)
    return sampled, f"sample products: {len(sampled)}/{len(sorted_rows)} = {products}"
