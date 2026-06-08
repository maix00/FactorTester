"""
test_3b_ic_returns.py
---------------------
Generate an Excel comparison for backend IC-test next-period returns.

This test is intentionally independent of test_3a.  It defines a minimal price
column factor, runs the backend CrossSectionIC path, extracts the RE
intermediate table, and writes an Excel workbook that compares backend RE
against formula-derived open-to-open returns from the backend price source.

Default audit:
  factor: ColumnRef(DataColumn.OPEN_ADJUSTED)
  $F:     1min
  SC:     DataColumn.OPEN_ADJUSTED
  RF:     2min
  S:      0  (open-to-open next return)
  Lag:    0
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, numbers

from sources.LocalCNFutures.CNFutures import CNFutures
from tools.data.DataColumn import DataColumn
from tools.factors.FactorFamily import FactorFamily
from tools.factors.FactorExpr import ColumnRef
from tools.factors.FactorTester import FactorTester
from tools.factors.tests.single_factor_test.ic import run_ic_for_factor

from tests.calc import (
    HEADER_FILL,
    MAIN_MINK_DIR,
    REMARK_FILL,
    REMARK_FONT,
    TEST_3B_DIR,
    remark_height,
)


DEFAULT_WORKERS = max(1, min(4, os.cpu_count() or 1))
DEFAULT_RF_MINUTES = 2
TOLERANCE = 1e-10

PRICE_SOURCE_SHEET = 'PRICE_SOURCE'
BACKEND_RE_SHEET = 'BACKEND_RE'
COMPARE_SHEET = 'COMPARE'

DATE_FORMAT = 'yyyy-mm-dd'
DATETIME_FORMAT = 'yyyy-mm-dd hh:mm:ss'
RETURN_NUMBER_FORMAT = '0.0000000000'

PRICE_DATA_START_ROW = 3
BACKEND_DATA_START_ROW = 3
COMPARE_START_ROW = 13


class _OpenAdjustedFactor(FactorFamily):
    source_freq = '1m'

    @staticmethod
    def factor_expr():
        return ColumnRef(DataColumn.OPEN_ADJUSTED)


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


def _write_header(ws, headers: list[str]) -> None:
    ws.append([
        _styled_cell(ws, h, fill=HEADER_FILL, font=REMARK_FONT)
        for h in headers
    ])


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


def _normalise_timestamp(value):
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert('Asia/Shanghai').tz_localize(None)
    return ts.to_pydatetime()


def _normalise_number(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def _product_name(product_id: str) -> str:
    if '.' in product_id:
        return product_id
    candidates = [
        path.stem
        for path in MAIN_MINK_DIR.glob(f'{product_id}.*.parquet')
        if path.name.split('.', 1)[0] == product_id
    ]
    if not candidates:
        raise RuntimeError(f'Cannot infer exchange for product {product_id}; pass full name like A.DCE')
    if len(candidates) > 1:
        raise RuntimeError(f'Multiple products match {product_id}: {", ".join(sorted(candidates))}')
    return candidates[0]


def _iter_products(products: Iterable[str] | None = None) -> list[str]:
    if products:
        return list(products)
    return ['A']


def _price_source(product: CNFutures) -> pd.Series:
    df = product.MIN1.get_and_adjust_cols([DataColumn.OPEN_ADJUSTED.name], copy=False)
    if DataColumn.OPEN_ADJUSTED.name not in df.columns:
        raise RuntimeError(f'{product.name}: missing OPEN_ADJUSTED source column')
    return pd.to_numeric(df[DataColumn.OPEN_ADJUSTED.name], errors='coerce')


def _backend_re(product: CNFutures, rf_minutes: int) -> pd.Series:
    tester = FactorTester(products=[product], logger_file=False)
    factor = _OpenAdjustedFactor().get_factor(**{'$F': '1min', '$Rev': '0'})
    factor.evaluate([product])
    params = {
        'FE': factor,
        'SC': DataColumn.OPEN_ADJUSTED,
        'RF': f'{rf_minutes}min',
        'S': 0,
        'Lag': 0,
        '$F': '1min',
    }
    _factors, _ic_series, _stats, re_table, _fe_table, _mask = run_ic_for_factor(tester, params, [factor])
    if product not in re_table.columns:
        raise RuntimeError(f'{product.name}: backend RE missing product column')
    return pd.to_numeric(re_table[product], errors='coerce')


def _write_price_source(ws, prices: pd.Series) -> int:
    remark = 'Backend price source for Excel expected-return formulas: OPEN_ADJUSTED at $F=1min.'
    _write_remark(ws, remark)
    _write_header(ws, ['trading_day', 'trade_time', 'open_price_adjusted', '_trade_time_key'])

    for row_idx, (idx, value) in enumerate(prices.items(), start=PRICE_DATA_START_ROW):
        day_value = idx[0] if isinstance(idx, tuple) else pd.Timestamp(idx).normalize()
        time_value = idx[-1] if isinstance(idx, tuple) else idx
        trading_day = _styled_cell(ws, _normalise_timestamp(day_value), number_format=DATE_FORMAT)
        trade_time = _styled_cell(
            ws,
            _normalise_timestamp(time_value),
            alignment=Alignment(horizontal='right'),
            number_format=DATETIME_FORMAT,
        )
        key = f'=TEXT(B{row_idx},"yyyy-mm-dd hh:mm:ss")'
        ws.append([trading_day, trade_time, _normalise_number(value), key])
    return len(prices)


def _write_backend_re(ws, returns: pd.Series) -> int:
    remark = 'Backend CrossSectionIC RE intermediate for SC=OPEN_ADJUSTED, S=0, Lag=0.'
    _write_remark(ws, remark)
    _write_header(ws, ['signal_trade_time', 'backend_re', '_trade_time_key'])

    for row_idx, (idx, value) in enumerate(returns.items(), start=BACKEND_DATA_START_ROW):
        signal_time = idx[-1] if isinstance(idx, tuple) else idx
        trade_time = _styled_cell(
            ws,
            _normalise_timestamp(signal_time),
            alignment=Alignment(horizontal='right'),
            number_format=DATETIME_FORMAT,
        )
        backend_value = _styled_cell(ws, _normalise_number(value), number_format=RETURN_NUMBER_FORMAT)
        key = f'=TEXT(A{row_idx},"yyyy-mm-dd hh:mm:ss")'
        ws.append([trade_time, backend_value, key])
    return len(returns)


def _write_compare(ws, backend_rows: int, price_rows: int, rf_minutes: int) -> None:
    compare_end_row = COMPARE_START_ROW + backend_rows - 1
    price_last_row = PRICE_DATA_START_ROW + price_rows - 1
    backend_last_row = BACKEND_DATA_START_ROW + backend_rows - 1

    remark = (
        'Excel formula comparison for backend IC RE.  RF_MINUTES means enter at '
        'the next 1min open and exit RF minutes after entry.'
    )
    _write_remark(ws, remark)
    ws.append(['RF_MINUTES', rf_minutes])
    ws.append(['tolerance', TOLERANCE])
    ws.append(['backend_re_rows', backend_rows])
    ws.append(['price_source_rows', price_rows])
    ws.append(['missing_signal_time', f'=COUNTIF(L{COMPARE_START_ROW}:L{compare_end_row},"MISSING")'])
    ws.append(['diff_rows', f'=COUNTIF(L{COMPARE_START_ROW}:L{compare_end_row},"FAIL")'])
    ws.append(['max_abs_diff', f'=MAX(K{COMPARE_START_ROW}:K{compare_end_row})'])
    ws.append(['overall', '=IF(AND(B6=0,B7=0),"PASS","FAIL")'])
    ws.append([])
    ws.append([])

    _write_header(
        ws,
        [
            '_backend_row',
            'signal_trade_time',
            'backend_re',
            '_price_row',
            'entry_row',
            'entry_trade_time',
            'entry_open_adjusted',
            'exit_row',
            'exit_trade_time',
            'expected_re_formula',
            'abs_diff',
            'status',
        ],
    )

    for row in range(COMPARE_START_ROW, compare_end_row + 1):
        backend_row = f'=ROW()-{COMPARE_START_ROW - BACKEND_DATA_START_ROW}'
        signal_time = _styled_cell(
            ws,
            f'=INDEX(BACKEND_RE!A:A,A{row})',
            alignment=Alignment(horizontal='right'),
            number_format=DATETIME_FORMAT,
        )
        backend_re = _styled_cell(ws, f'=INDEX(BACKEND_RE!B:B,A{row})', number_format=RETURN_NUMBER_FORMAT)
        price_row = f'=IFERROR(MATCH(TEXT(B{row},"yyyy-mm-dd hh:mm:ss"),PRICE_SOURCE!$D:$D,0),"")'
        entry_row = f'=IF(D{row}="","",D{row}+1)'
        entry_time = _styled_cell(
            ws,
            f'=IF(E{row}="","",INDEX(PRICE_SOURCE!$B:$B,E{row}))',
            alignment=Alignment(horizontal='right'),
            number_format=DATETIME_FORMAT,
        )
        entry_open = _styled_cell(
            ws,
            f'=IF(E{row}="","",INDEX(PRICE_SOURCE!$C:$C,E{row}))',
            number_format=RETURN_NUMBER_FORMAT,
        )
        exit_row = f'=IF(D{row}="","",D{row}+$B$2+1)'
        exit_time = _styled_cell(
            ws,
            f'=IF(OR(H{row}="",H{row}>{price_last_row}),"",INDEX(PRICE_SOURCE!$B:$B,H{row}))',
            alignment=Alignment(horizontal='right'),
            number_format=DATETIME_FORMAT,
        )
        expected = _styled_cell(
            ws,
            f'=IF(OR(H{row}="",H{row}>{price_last_row}),"",INDEX(PRICE_SOURCE!$C:$C,H{row})/G{row}-1)',
            number_format=RETURN_NUMBER_FORMAT,
        )
        abs_diff = f'=IF(AND(C{row}="",J{row}=""),0,IF(OR(C{row}="",J{row}=""),"",ABS(C{row}-J{row})))'
        status = f'=IF(D{row}="","MISSING",IF(AND(C{row}="",J{row}=""),"PASS",IF(OR(C{row}="",J{row}=""),"FAIL",IF(K{row}<=$B$3,"PASS","FAIL"))))'
        ws.append([
            backend_row,
            signal_time,
            backend_re,
            price_row,
            entry_row,
            entry_time,
            entry_open,
            exit_row,
            exit_time,
            expected,
            abs_diff,
            status,
        ])

    ws.append([])
    ws.append(['_backend_last_row', backend_last_row])


def _style_workbook(path: Path) -> None:
    wb = load_workbook(path)
    try:
        widths = {
            PRICE_SOURCE_SHEET: {'A': 14, 'B': 22, 'C': 24, 'D': 22},
            BACKEND_RE_SHEET: {'A': 22, 'B': 18, 'C': 22},
            COMPARE_SHEET: {
                'A': 12, 'B': 22, 'C': 18, 'D': 12, 'E': 12, 'F': 22,
                'G': 22, 'H': 12, 'I': 22, 'J': 22, 'K': 16, 'L': 12,
            },
        }
        for ws in wb.worksheets:
            ws.freeze_panes = 'A3' if ws.title != COMPARE_SHEET else f'A{COMPARE_START_ROW}'
            for col, width in widths.get(ws.title, {}).items():
                ws.column_dimensions[col].width = width
    finally:
        wb.save(path)
        wb.close()


def process_product(product_id: str, rf_minutes: int = DEFAULT_RF_MINUTES) -> Path:
    product_name = _product_name(product_id)
    product = CNFutures(product_name)
    prices = _price_source(product)
    returns = _backend_re(product, rf_minutes=rf_minutes)

    TEST_3B_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TEST_3B_DIR / f'{product.code}.xlsx'

    print(f'  Processing: {product.name} RF={rf_minutes}min...', end='', flush=True)
    wb = Workbook(write_only=True)
    price_ws = wb.create_sheet(PRICE_SOURCE_SHEET)
    backend_ws = wb.create_sheet(BACKEND_RE_SHEET)
    compare_ws = wb.create_sheet(COMPARE_SHEET)

    price_rows = _write_price_source(price_ws, prices)
    backend_rows = _write_backend_re(backend_ws, returns)
    _write_compare(compare_ws, backend_rows=backend_rows, price_rows=price_rows, rf_minutes=rf_minutes)

    wb.save(out_path)
    _style_workbook(out_path)
    print(f' OK ({backend_rows} backend RE rows, {price_rows} price rows)')
    return out_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description='Generate test_3b backend IC RE comparisons.')
    parser.add_argument('products', nargs='*', help='Optional product ids, e.g. A or A.DCE')
    parser.add_argument('--rf-minutes', type=int, default=DEFAULT_RF_MINUTES)
    parser.add_argument(
        '--workers',
        type=int,
        default=int(os.environ.get('TEST_3B_WORKERS', DEFAULT_WORKERS)),
        help='Number of product workbooks to generate in parallel.',
    )
    args = parser.parse_args(argv)

    products = _iter_products(args.products)
    print('test_3b: Excel comparison against backend IC RE intermediate')
    print(f'Output: {TEST_3B_DIR}')
    print(f'RF    : {args.rf_minutes}min')
    print(f'Workers: {args.workers}')

    errors: list[tuple[str, Exception]] = []
    if args.workers <= 1 or len(products) <= 1:
        for product in products:
            try:
                process_product(product, rf_minutes=args.rf_minutes)
            except Exception as exc:
                errors.append((product, exc))
                print(f' ERROR {exc}')
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(process_product, product, args.rf_minutes): product for product in products}
            for future in as_completed(futures):
                product = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    errors.append((product, exc))
                    print(f'  {product}: ERROR {exc}')

    if errors:
        print(f'\nFailed products: {len(errors)}')
        for product, exc in errors[:20]:
            print(f'  {product}: {exc}')
        sys.exit(1)


def test_backend_ic_re_workbook_for_a_product():
    out_path = process_product('A', rf_minutes=DEFAULT_RF_MINUTES)
    wb = load_workbook(out_path, read_only=True, data_only=False)
    try:
        assert wb.sheetnames == [PRICE_SOURCE_SHEET, BACKEND_RE_SHEET, COMPARE_SHEET]
        price_ws = wb[PRICE_SOURCE_SHEET]
        backend_ws = wb[BACKEND_RE_SHEET]
        compare_ws = wb[COMPARE_SHEET]

        assert price_ws.cell(2, 3).value == 'open_price_adjusted'
        assert backend_ws.cell(2, 2).value == 'backend_re'
        assert compare_ws.cell(2, 1).value == 'RF_MINUTES'
        assert compare_ws.cell(2, 2).value == DEFAULT_RF_MINUTES
        assert compare_ws.cell(COMPARE_START_ROW - 1, 6).value == 'entry_trade_time'
        assert compare_ws.cell(COMPARE_START_ROW - 1, 8).value == 'exit_row'
        assert compare_ws.cell(COMPARE_START_ROW, 5).value == f'=IF(D{COMPARE_START_ROW}="","",D{COMPARE_START_ROW}+1)'
        assert f'D{COMPARE_START_ROW}+$B$2+1' in compare_ws.cell(COMPARE_START_ROW, 8).value
        assert f'INDEX(PRICE_SOURCE!$C:$C,H{COMPARE_START_ROW})/G{COMPARE_START_ROW}-1' in compare_ws.cell(COMPARE_START_ROW, 10).value
    finally:
        wb.close()


if __name__ == '__main__':
    main()
