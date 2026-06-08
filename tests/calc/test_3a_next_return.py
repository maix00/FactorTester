import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, numbers
from openpyxl.utils import get_column_letter

from tests.calc import (
    FORMULA_FILL,
    HEADER_FILL,
    REMARK_FILL,
    REMARK_FONT,
    TEST_2A_DIR,
    TEST_3A_DIR,
    remark_height,
)

"""
test_3a_next_return.py
----------------------
Generate an Excel workbook that verifies next-period open-to-open returns from
the full test_2a MAIN continuous-main sequence.

Input:
  data/test/test_2a/{prod}.xlsx, sheet MAIN, cached values after WPS/Excel save.

Output:
  data/test/test_3a/{prod}.xlsx

Workbook layout:
  MAIN_VALUES:
    Full cached MAIN values copied from test_2a.  This keeps every minute bar,
    so 1min, 30min, 1d, or other future return horizons can be audited without
    clipping a window boundary.

  OPEN_TO_OPEN_1MIN:
    Formula-only audit table for the current backend default path:
      OPEN_ADJUSTED = open_price * adjustment_mul + adjustment_add
      NEXT_OPEN_TO_OPEN_ADJUSTED_1MIN
        = next OPEN_ADJUSTED / current OPEN_ADJUSTED - 1

Python copies source values and writes formula text.  It does not hardcode
Python-calculated return results into Excel.
"""


DEFAULT_WORKERS = max(1, min(4, os.cpu_count() or 1))

MAIN_SHEET = 'MAIN'
MAIN_VALUES_SHEET = 'MAIN_VALUES'
RETURN_SHEET = 'OPEN_TO_OPEN_1MIN'

MAIN_HEADER_ROW = 2
MAIN_DATA_START_ROW = 3
MAIN_VALUES_HEADER_ROW = 2
MAIN_VALUES_DATA_START_ROW = 3
RETURN_HEADER_ROW = 2
RETURN_DATA_START_ROW = 3

REQUIRED_MAIN_COLUMNS = [
    'trading_day',
    'trade_time',
    'unique_instrument_id',
    'open_price',
    'adjustment_mul',
    'adjustment_add',
]

RETURN_HEADERS = [
    '_main_row',
    'trading_day',
    'trade_time',
    'unique_instrument_id',
    'open_price',
    'adjustment_mul',
    'adjustment_add',
    'open_price_adjusted_formula',
    'next_trade_time',
    'next_unique_instrument_id',
    'next_open_price_adjusted_formula',
    'next_open_to_open_adjusted_1min',
]


def _styled_cell(ws, value, *, fill=None, font=None, alignment=None, number_format=None):
    cell = WriteOnlyCell(ws, value=value)
    if fill is not None:
        cell.fill = fill
    if font is not None:
        cell.font = font
    if alignment is not None:
        cell.alignment = alignment
    if number_format is not None:
        cell.number_format = number_format
    return cell


def _write_remark(ws, text: str) -> None:
    ws.append([
        _styled_cell(
            ws,
            text,
            fill=REMARK_FILL,
            font=REMARK_FONT,
            alignment=Alignment(wrap_text=True, vertical='top'),
        )
    ])
    ws.row_dimensions[1].height = remark_height(text)


def _write_header(ws, headers: list[str]) -> None:
    ws.append([
        _styled_cell(ws, h, fill=HEADER_FILL, font=REMARK_FONT)
        for h in headers
    ])


def _set_sheet_layout(ws) -> None:
    ws.freeze_panes = 'A3'
    widths = {
        'A': 12,
        'B': 16,
        'C': 22,
        'D': 24,
        'E': 13,
        'F': 14,
        'G': 14,
        'H': 24,
        'I': 22,
        'J': 24,
        'K': 28,
        'L': 28,
    }
    for col, width in widths.items():
        ws.column_dimensions[col].width = width


def _normalise_header(value) -> str:
    return '' if value is None else str(value)


def _col_index(headers: list, name: str) -> int:
    normalised = [_normalise_header(h) for h in headers]
    try:
        return normalised.index(name) + 1
    except ValueError as exc:
        raise RuntimeError(f'MAIN missing required column: {name}') from exc


def _normalise_value(value):
    if hasattr(value, 'to_pydatetime'):
        return value.to_pydatetime()
    return value


def _iter_test2a_files(products: Iterable[str] | None = None) -> list[Path]:
    if products:
        return [TEST_2A_DIR / f'{prod}.xlsx' for prod in products]
    return sorted(TEST_2A_DIR.glob('*.xlsx'))


def _copy_main_values(src_path: Path, ws_out) -> tuple[list[str], int]:
    value_wb = load_workbook(src_path, read_only=True, data_only=True)
    try:
        if MAIN_SHEET not in value_wb.sheetnames:
            raise RuntimeError(f'{src_path.name} has no MAIN sheet')

        value_ws = value_wb[MAIN_SHEET]
        headers = [
            _normalise_header(value_ws.cell(MAIN_HEADER_ROW, col).value)
            for col in range(1, value_ws.max_column + 1)
        ]
        if not headers or not headers[0] or value_ws.cell(MAIN_DATA_START_ROW, 1).value is None:
            raise RuntimeError(
                f'{src_path.name} MAIN has no cached values. '
                'Open test_2a workbook in WPS/Excel, let formulas calculate, save it, then rerun test_3a.'
            )
        for col in REQUIRED_MAIN_COLUMNS:
            _col_index(headers, col)

        remark = (
            'Full cached MAIN values copied from test_2a. '
            'Derived return columns are written on OPEN_TO_OPEN_1MIN as Excel formulas.'
        )
        _set_sheet_layout(ws_out)
        _write_remark(ws_out, remark)
        _write_header(ws_out, headers)

        row_count = 0
        for row in value_ws.iter_rows(
            min_row=MAIN_DATA_START_ROW,
            max_row=value_ws.max_row,
            min_col=1,
            max_col=value_ws.max_column,
            values_only=True,
        ):
            ws_out.append([_normalise_value(v) for v in row])
            row_count += 1

        return headers, row_count
    finally:
        value_wb.close()


def _write_return_formulas(ws_out, headers: list[str], main_rows: int) -> None:
    remark = (
        'Excel formula audit for NEXT_OPEN_TO_OPEN_ADJUSTED with $F=1min. '
        'The return formula references the next row in MAIN_VALUES; no Python-computed return is hardcoded.'
    )
    _set_sheet_layout(ws_out)
    _write_remark(ws_out, remark)
    _write_header(ws_out, RETURN_HEADERS)

    source_cols = {name: get_column_letter(_col_index(headers, name)) for name in REQUIRED_MAIN_COLUMNS}
    last_return_row = RETURN_DATA_START_ROW + main_rows - 1

    for row in range(RETURN_DATA_START_ROW, last_return_row + 1):
        main_row = MAIN_VALUES_DATA_START_ROW + (row - RETURN_DATA_START_ROW)
        next_main_row = main_row + 1

        current_open_adjusted = _styled_cell(
            ws_out,
            f'=MAIN_VALUES!${source_cols["open_price"]}{main_row}'
            f'*MAIN_VALUES!${source_cols["adjustment_mul"]}{main_row}'
            f'+MAIN_VALUES!${source_cols["adjustment_add"]}{main_row}',
            fill=FORMULA_FILL,
        )
        next_open_adjusted = _styled_cell(
            ws_out,
            f'=IF(A{row}=A${last_return_row},"",'
            f'MAIN_VALUES!${source_cols["open_price"]}{next_main_row}'
            f'*MAIN_VALUES!${source_cols["adjustment_mul"]}{next_main_row}'
            f'+MAIN_VALUES!${source_cols["adjustment_add"]}{next_main_row})',
            fill=FORMULA_FILL,
        )
        next_return = _styled_cell(
            ws_out,
            f'=IF(K{row}="","",K{row}/H{row}-1)',
            fill=FORMULA_FILL,
            number_format=numbers.FORMAT_PERCENTAGE_00,
        )

        trade_time = _styled_cell(
            ws_out,
            f'=MAIN_VALUES!${source_cols["trade_time"]}{main_row}',
            alignment=Alignment(horizontal='right'),
            number_format='yyyy-mm-dd hh:mm:ss',
        )
        next_trade_time = _styled_cell(
            ws_out,
            f'=IF(A{row}=A${last_return_row},"",MAIN_VALUES!${source_cols["trade_time"]}{next_main_row})',
            alignment=Alignment(horizontal='right'),
            number_format='yyyy-mm-dd hh:mm:ss',
        )

        ws_out.append([
            main_row,
            f'=MAIN_VALUES!${source_cols["trading_day"]}{main_row}',
            trade_time,
            f'=MAIN_VALUES!${source_cols["unique_instrument_id"]}{main_row}',
            f'=MAIN_VALUES!${source_cols["open_price"]}{main_row}',
            f'=MAIN_VALUES!${source_cols["adjustment_mul"]}{main_row}',
            f'=MAIN_VALUES!${source_cols["adjustment_add"]}{main_row}',
            current_open_adjusted,
            next_trade_time,
            f'=IF(A{row}=A${last_return_row},"",MAIN_VALUES!${source_cols["unique_instrument_id"]}{next_main_row})',
            next_open_adjusted,
            next_return,
        ])


def process_product(test2a_xlsx: Path) -> int:
    prod = test2a_xlsx.stem
    if not test2a_xlsx.exists():
        print(f'  test_2a file not found: {test2a_xlsx.name}, skipping')
        return 0

    TEST_3A_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TEST_3A_DIR / f'{prod}.xlsx'

    print(f'  Processing: {prod}...', end='', flush=True)
    wb = Workbook(write_only=True)
    main_ws = wb.create_sheet(MAIN_VALUES_SHEET)
    return_ws = wb.create_sheet(RETURN_SHEET)

    headers, main_rows = _copy_main_values(test2a_xlsx, main_ws)
    _write_return_formulas(return_ws, headers=headers, main_rows=main_rows)

    wb.save(out_path)
    print(f' OK ({main_rows} MAIN rows)')
    return main_rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description='Generate test_3a next open-to-open return workbooks.')
    parser.add_argument('products', nargs='*', help='Optional product ids, e.g. A RB IF')
    parser.add_argument(
        '--workers',
        type=int,
        default=int(os.environ.get('TEST_3A_WORKERS', DEFAULT_WORKERS)),
        help='Number of product workbooks to generate in parallel.',
    )
    args = parser.parse_args(argv)

    files = _iter_test2a_files(args.products)
    if not files:
        print(f'No test_2a xlsx files found in {TEST_2A_DIR}')
        return

    print('test_3a: Excel NEXT_OPEN_TO_OPEN_ADJUSTED comparison source')
    print(f'Input : {TEST_2A_DIR}')
    print(f'Output: {TEST_3A_DIR}')
    print(f'Workers: {args.workers}')

    errors: list[tuple[str, Exception]] = []
    if args.workers <= 1 or len(files) <= 1:
        for path in files:
            try:
                process_product(path)
            except Exception as exc:
                errors.append((path.stem, exc))
                print(f' ERROR {exc}')
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(process_product, path): path for path in files}
            for future in as_completed(futures):
                path = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    errors.append((path.stem, exc))
                    print(f'  {path.stem}: ERROR {exc}')

    if errors:
        print(f'\nFailed products: {len(errors)}')
        for prod, exc in errors[:20]:
            print(f'  {prod}: {exc}')
        sys.exit(1)


def test_return_formula_workbook_for_a_product():
    main_rows = process_product(TEST_2A_DIR / 'A.xlsx')

    out_path = TEST_3A_DIR / 'A.xlsx'
    wb = load_workbook(out_path, read_only=True, data_only=False)
    try:
        assert wb.sheetnames == [MAIN_VALUES_SHEET, RETURN_SHEET]
        main_ws = wb[MAIN_VALUES_SHEET]
        return_ws = wb[RETURN_SHEET]
        headers = next(main_ws.iter_rows(
            min_row=MAIN_VALUES_HEADER_ROW,
            max_row=MAIN_VALUES_HEADER_ROW,
            values_only=True,
        ))
        assert 'open_price' in headers
        assert 'adjustment_mul' in headers
        assert 'adjustment_add' in headers
        assert main_rows > 1000
        assert return_ws.cell(RETURN_HEADER_ROW, 12).value == 'next_open_to_open_adjusted_1min'
        assert return_ws.cell(RETURN_DATA_START_ROW, 8).value.startswith('=MAIN_VALUES!')
        assert '/H3-1' in return_ws.cell(RETURN_DATA_START_ROW, 12).value
        last_row = RETURN_DATA_START_ROW + main_rows - 1
        assert return_ws.cell(last_row, 12).value == f'=IF(K{last_row}="","",K{last_row}/H{last_row}-1)'
    finally:
        wb.close()


if __name__ == '__main__':
    main()
