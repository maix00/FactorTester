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
  RE:     NextReturns(SC=OPEN_ADJUSTED, RF=2min, S=0)
  Lag:    0
"""

from __future__ import annotations

import argparse
import datetime
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
from openpyxl.utils.datetime import from_excel

from sources.LocalCNFutures.CNFutures import CNFutures
from tools.data.types.DataColumn import DataColumn
from tools.factors.FactorFamily import FactorFamily
from tools.factors.FactorExpr import ColumnRef
from tools.factors.FactorTester import FactorTester
from tools.factors.tests.NextReturns import NextReturns
from tools.factors.tests.single_factor_test.ic import run_ic_for_factor

from tests.calc import (
    HEADER_FILL,
    MAIN_MINK_DIR,
    REMARK_FILL,
    REMARK_FONT,
    TEST_3A_DIR,
    TEST_3B_DIR,
    remark_height,
)


DEFAULT_WORKERS = max(1, min(4, os.cpu_count() or 1))
DEFAULT_RF_MINUTES = 2
TOLERANCE = 1e-10

TEST_3A_RETURNS_SHEET = 'TEST_3A_RETURNS'
BACKEND_RE_SHEET = 'BACKEND_RE'
COMPARE_SHEET = 'COMPARE'

DATE_FORMAT = 'yyyy-mm-dd'
DATETIME_FORMAT = 'yyyy-mm-dd hh:mm:ss'
RETURN_NUMBER_FORMAT = '0.0000000000'

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


def _ts_to_datetime(idx):  # -> datetime.datetime | NaT, but NaTType not in stubs
    if isinstance(idx, datetime.datetime):
        return idx
    return pd.Timestamp(idx).to_pydatetime()


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


def _backend_re(product: CNFutures, rf_minutes: int) -> pd.Series:
    tester = FactorTester(products=[product], logger_file=False)
    factor = _OpenAdjustedFactor().get_factor(**{'$F': '1min', '$Rev': '0'})
    factor.evaluate([product])
    next_returns = NextReturns().get_factor(
        SC=DataColumn.OPEN_ADJUSTED,
        RF=f'{rf_minutes}min',
        S=0,
        **{'$F': '1min', '$Rev': '0'},
    )
    params = {
        'FE': factor,
        'RE': next_returns,
        'Lag': 0,
        '$F': '1min',
    }
    _factors, _ic_series, _stats, re_table, _fe_table, _mask = run_ic_for_factor(tester, params, [factor])
    if product not in re_table.columns:
        raise RuntimeError(f'{product.name}: backend RE missing product column')
    return pd.Series(pd.to_numeric(re_table[product], errors='coerce'))


def _read_test3a_rf(test3a_path: Path) -> int | None:
    """从 test_3a OPEN_TO_OPEN_RF sheet B2 读取 RF_MINUTES 值。"""
    if not test3a_path.exists():
        return None
    wb = load_workbook(test3a_path, read_only=True, data_only=True)
    try:
        if 'OPEN_TO_OPEN_RF' not in wb.sheetnames:
            return None
        rf_value = wb['OPEN_TO_OPEN_RF']['B2'].value
        if rf_value is None:
            return None
        return int(rf_value)
    finally:
        wb.close()


def _read_test3a_returns(test3a_path: Path) -> pd.DataFrame | None:
    """从 test_3a OPEN_TO_OPEN_RF sheet 读取 signal_trade_time 和 next_open_to_open_adjusted_rf。
    
    返回 DataFrame，index=signal_trade_time，单列 'test3a_return'。
    """
    if not test3a_path.exists():
        return None
    wb = load_workbook(test3a_path, read_only=True, data_only=True)
    try:
        if 'OPEN_TO_OPEN_RF' not in wb.sheetnames:
            return None
        ws = wb['OPEN_TO_OPEN_RF']
        
        # 读 header row 3，确认列位置
        headers = [ws.cell(3, c).value for c in range(1, ws.max_column + 1)]
        try:
            time_col = headers.index('signal_trade_time') + 1
            ret_col = headers.index('next_open_to_open_adjusted_rf') + 1
        except ValueError:
            return None
        
        # 从 row 4 开始读数据
        # 注意：openpyxl data_only 模式下，日期类型存为 float（Excel 序列号），
        # 需要用 from_excel() 转换
        times = []
        returns = []
        for row in ws.iter_rows(min_row=4, max_row=ws.max_row, min_col=time_col, max_col=ret_col, values_only=True):
            t = row[0]
            r = row[ret_col - time_col]
            if t is None:
                continue
            t = from_excel(t) if isinstance(t, (int, float)) else t
            times.append(_normalise_timestamp(t))
            returns.append(_normalise_number(r))
        
        if not times:
            return None
        return pd.DataFrame({'test3a_return': returns}, index=pd.DatetimeIndex(times))
    finally:
        wb.close()


def _write_test3a_returns(ws, returns: pd.DataFrame) -> int:
    """将 test_3a 的收益率写入 sheet。"""
    remark = 'test_3a OPEN_TO_OPEN_RF: next_open_to_open_adjusted_rf extracted from test_3a workbook.'
    _write_remark(ws, remark)
    _write_header(ws, ['signal_trade_time', 'test3a_return', '_trade_time_key'])

    for row_idx, (idx, row) in enumerate(returns.iterrows(), start=3):
        trade_time = _styled_cell(
            ws, _ts_to_datetime(idx),
            alignment=Alignment(horizontal='right'),
            number_format=DATETIME_FORMAT,
        )
        ret_val = _styled_cell(ws, _normalise_number(row['test3a_return']), number_format=RETURN_NUMBER_FORMAT)
        key = f'=TEXT(A{row_idx},"yyyy-mm-dd hh:mm:ss")'
        ws.append([trade_time, ret_val, key])
    return len(returns)


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


def _write_compare(ws, backend_rows: int, test3a_rows: int, rf_minutes: int) -> None:
    compare_end_row = COMPARE_START_ROW + backend_rows - 1

    remark = (
        'Excel formula comparison: test_3a next_open_to_open_adjusted_rf vs backend IC RE.  '
        'RF read from test_3a OPEN_TO_OPEN_RF!B2.'
    )
    _write_remark(ws, remark)
    ws.append(['RF_MINUTES', rf_minutes])
    ws.append(['tolerance', TOLERANCE])
    ws.append(['backend_re_rows', backend_rows])
    ws.append(['test3a_return_rows', test3a_rows])
    ws.append(['missing_signal_time', f'=COUNTIF(G{COMPARE_START_ROW}:G{compare_end_row},"MISSING")'])
    ws.append(['diff_rows', f'=COUNTIF(G{COMPARE_START_ROW}:G{compare_end_row},"FAIL")'])
    ws.append(['max_abs_diff', f'=MAX(F{COMPARE_START_ROW}:F{compare_end_row})'])
    ws.append(['overall', '=IF(AND(B6=0,B7=0),"PASS","FAIL")'])
    ws.append([])
    ws.append([])

    _write_header(
        ws,
        [
            '_backend_row',
            'signal_trade_time',
            'backend_re',
            'test3a_return',
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
        test3a_return = _styled_cell(
            ws,
            f'=IFERROR(INDEX(TEST_3A_RETURNS!B:B,MATCH(TEXT(B{row},"yyyy-mm-dd hh:mm:ss"),TEST_3A_RETURNS!$C:$C,0)),"")',
            number_format=RETURN_NUMBER_FORMAT,
        )
        abs_diff = f'=IF(AND(C{row}="",D{row}=""),0,IF(OR(C{row}="",D{row}=""),"",ABS(C{row}-D{row})))'
        status = f'=IF(D{row}="","MISSING",IF(AND(C{row}="",D{row}=""),"PASS",IF(OR(C{row}="",D{row}=""),"FAIL",IF(E{row}<=$B$3,"PASS","FAIL"))))'
        ws.append([
            backend_row,
            signal_time,
            backend_re,
            test3a_return,
            abs_diff,
            status,
        ])


def _style_workbook(path: Path) -> None:
    wb = load_workbook(path)
    try:
        widths = {
            TEST_3A_RETURNS_SHEET: {'A': 22, 'B': 18, 'C': 22},
            BACKEND_RE_SHEET: {'A': 22, 'B': 18, 'C': 22},
            COMPARE_SHEET: {
                'A': 12, 'B': 22, 'C': 18, 'D': 18, 'E': 16, 'F': 12,
            },
        }
        for ws in wb.worksheets:
            ws.freeze_panes = 'A3' if ws.title != COMPARE_SHEET else f'A{COMPARE_START_ROW}'
            for col, width in widths.get(ws.title, {}).items():
                ws.column_dimensions[col].width = width
    finally:
        wb.save(path)
        wb.close()


def process_product(product_id: str, rf_minutes: int | None = None) -> Path:
    product_name = _product_name(product_id)
    product = CNFutures(product_name)

    test3a_path = TEST_3A_DIR / f'{product.code}.xlsx'

    # 优先从 test_3a 读取 RF
    test3a_rf = _read_test3a_rf(test3a_path)
    if test3a_rf is not None:
        rf = test3a_rf
    elif rf_minutes is not None:
        rf = rf_minutes
    else:
        rf = DEFAULT_RF_MINUTES

    # 读取 test_3a 收益率
    test3a_returns = _read_test3a_returns(test3a_path)
    has_test3a = test3a_returns is not None and len(test3a_returns) > 0

    # 后端 RE
    returns = _backend_re(product, rf_minutes=rf)

    TEST_3B_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TEST_3B_DIR / f'{product.code}.xlsx'

    print(f'  Processing: {product.name} RF={rf}min (test3a_rf={test3a_rf})...', end='', flush=True)
    wb = Workbook(write_only=True)
    test3a_ws = wb.create_sheet(TEST_3A_RETURNS_SHEET) if has_test3a else None
    backend_ws = wb.create_sheet(BACKEND_RE_SHEET)
    compare_ws = wb.create_sheet(COMPARE_SHEET)

    test3a_rows = 0
    if has_test3a and test3a_ws is not None and test3a_returns is not None:
        test3a_rows = _write_test3a_returns(test3a_ws, test3a_returns)
    backend_rows = _write_backend_re(backend_ws, returns)
    _write_compare(compare_ws, backend_rows=backend_rows, test3a_rows=test3a_rows, rf_minutes=rf)

    wb.save(out_path)
    _style_workbook(out_path)
    print(f' OK ({backend_rows} backend RE rows, {test3a_rows} test_3a rows)')
    return out_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description='Generate test_3b backend IC RE comparisons.')
    parser.add_argument('products', nargs='*', help='Optional product ids, e.g. A or A.DCE')
    parser.add_argument('--rf-minutes', type=int, default=None, help='Fallback RF if no test_3a exists')
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
    expected_rf = _read_test3a_rf(TEST_3A_DIR / 'A.xlsx') or DEFAULT_RF_MINUTES
    wb = load_workbook(out_path, read_only=True, data_only=False)
    try:
        assert wb.sheetnames == [TEST_3A_RETURNS_SHEET, BACKEND_RE_SHEET, COMPARE_SHEET]
        backend_ws = wb[BACKEND_RE_SHEET]
        compare_ws = wb[COMPARE_SHEET]

        assert backend_ws.cell(2, 2).value == 'backend_re'
        assert compare_ws.cell(2, 1).value == 'RF_MINUTES'
        assert compare_ws.cell(2, 2).value == expected_rf
        assert compare_ws.cell(COMPARE_START_ROW - 1, 1).value == '_backend_row'
        assert compare_ws.cell(COMPARE_START_ROW - 1, 2).value == 'signal_trade_time'
        assert compare_ws.cell(COMPARE_START_ROW - 1, 6).value == 'status'
        assert compare_ws.cell(COMPARE_START_ROW, 1).value == f'=ROW()-{COMPARE_START_ROW - BACKEND_DATA_START_ROW}'
        assert f'INDEX(BACKEND_RE!A:A,A{COMPARE_START_ROW})' in str(compare_ws.cell(COMPARE_START_ROW, 2).value)
        assert f'INDEX(TEST_3A_RETURNS!B:B,MATCH(TEXT(B{COMPARE_START_ROW},"yyyy-mm-dd hh:mm:ss"),TEST_3A_RETURNS!$C:$C,0))' in str(compare_ws.cell(COMPARE_START_ROW, 4).value)
        assert f'IF(E{COMPARE_START_ROW}<=$B$3,"PASS","FAIL")' in str(compare_ws.cell(COMPARE_START_ROW, 6).value)
    finally:
        wb.close()


if __name__ == '__main__':
    main()
