# pyright: reportMissingImports=false, reportMissingModuleSource=false
"""
test_4a_shift.py
----------------
验证 ShiftOp（时序位移算子 X.shift(N)）的行为。

从 test_2a MAIN sheet 读取主力连续序列（含复权因子adj_mul），
用后端 ShiftOp 分别计算 10min / 5bar / 1day 三种位移，
写入 Excel 让用户手工验算。

Sheet 结构：
  PRICE    — trade_time / open_price / adj_mul / open_adj（Excel公式）
  BACKEND  — 后端 ShiftOp 结果（每种 shift 一列）
  COMPARE  — PRICE Excel shift公式 与 BACKEND 对比
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment
from openpyxl.utils.datetime import from_excel

from sources.LocalCNFutures.CNFutures import CNFutures
from tools.data.DataColumn import DataColumn
from tools.data.DataFreq import DataFreq
from tools.factors.FactorExpr import ColumnRef, EvaluateContext, ShiftOp
from tools.factors.FactorFamily import FactorFamily
from tools.factors.FactorTester import FactorTester
from tools.factors.expr.rolling import _resolve_windows
from tools.factors.expr.leaf import ConstExpr

from tests.calc import (
    HEADER_FILL,
    MAIN_MINK_DIR,
    COMMENT_FONT,
    REMARK_FILL,
    REMARK_FONT,
    TEST_2A_DIR,
    TEST_4A_DIR,
    remark_height,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
PRICE_SHEET = 'PRICE'
BACKEND_SHEET = 'BACKEND'
COMPARE_SHEET = 'COMPARE'

DT_FMT = 'yyyy-mm-dd hh:mm:ss'
NUM_FMT = '0.0000000000'

# 三种 shift 配置：(名称, shift值)
SHIFTS = [
    ('SHIFT_10MIN', '10min'),
    ('SHIFT_5BAR', 5),
    ('SHIFT_1DAY', '1day'),
]

# MAIN sheet 列索引（0-based, 来自 test_2a）
COL_TRADING_DAY = 0
COL_TRADE_TIME = 1
COL_OPEN_PRICE = 6
COL_ADJ_MUL = 21

DATA_ROW_OFFSET = 2  # row 1 = remark, row 2 = header → 数据从 row 3 开始
BACKEND_DATA_START_ROW = 3
COMPARE_START_ROW = 4


# ---------------------------------------------------------------------------
# 最小因子类
# ---------------------------------------------------------------------------
class _OpenAdjustedFactor(FactorFamily):

    @staticmethod
    def factor_expr():
        return ColumnRef(DataColumn.OPEN_ADJUSTED)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
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
        _styled_cell(ws, text, fill=REMARK_FILL, font=COMMENT_FONT,
                     alignment=Alignment(wrap_text=True, vertical='top'))
    ])
    ws.row_dimensions[1].height = remark_height(text)


def _write_header(ws, headers: list[str]) -> None:
    ws.append([
        _styled_cell(ws, h, fill=HEADER_FILL, font=REMARK_FONT) for h in headers
    ])


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


def _normalise_excel_datetime(value):
    if hasattr(value, 'to_pydatetime'):
        return value.to_pydatetime()
    if isinstance(value, (int, float)):
        return from_excel(value)
    return value


def _normalise_series_index(series: pd.Series) -> pd.Series:
    index = series.index.get_level_values(-1) if isinstance(series.index, pd.MultiIndex) else series.index
    ts_index = pd.DatetimeIndex(index)
    if ts_index.tz is not None:
        ts_index = ts_index.tz_convert('Asia/Shanghai').tz_localize(None)
    series = series.copy()
    series.index = ts_index
    return series


def _shift_bars(product: CNFutures) -> dict[str, int]:
    result: dict[str, int] = {}
    for name, shift_val in SHIFTS:
        if shift_val == '1day':
            continue
        common, periods, _product_periods = _resolve_windows(
            shift_val,
            DataFreq('1min'),
            [product],
        )
        if not common:
            raise RuntimeError(f'{product.name}: shift {name} does not resolve to common bars')
        result[name] = int(periods)
    return result


def _read_test2a_main(prod_path: Path) -> tuple[list, list, list, list] | None:
    """从 test_2a MAIN sheet 读缓存公式值（data_only=True）。
    返回 (trading_days, times, open_prices, adj_muls)。
    """
    if not prod_path.exists():
        return None
    wb = load_workbook(prod_path, read_only=True, data_only=True)
    try:
        ws = wb['MAIN']
        trading_days = []
        times = []
        opens = []
        adjs = []
        for row in ws.iter_rows(min_row=3, values_only=True):
            d = row[COL_TRADING_DAY] if len(row) > COL_TRADING_DAY else None
            t = row[COL_TRADE_TIME] if len(row) > COL_TRADE_TIME else None
            o = row[COL_OPEN_PRICE] if len(row) > COL_OPEN_PRICE else None
            a = row[COL_ADJ_MUL] if len(row) > COL_ADJ_MUL else None
            if t is None:
                break
            trading_days.append(_normalise_excel_datetime(d))
            times.append(_normalise_excel_datetime(t))
            opens.append(o)
            adjs.append(a)
        if not times:
            return None
        return trading_days, times, opens, adjs
    finally:
        wb.close()


def _price_time_key_formula(last_row: int) -> str:
    return f'=TEXT(A3:A{last_row},"yyyy-mm-dd")&"|"&TEXT(B3:B{last_row},"hh:mm:ss")'


def _open_adjusted_formula(last_row: int) -> str:
    return f'=D3:D{last_row}*E3:E{last_row}'


def _shift_bars_formula(n_bars: int) -> str:
    return f'=LET(x,F3#,VSTACK(MAKEARRAY({n_bars},1,LAMBDA(r,c,"")),DROP(x,-{n_bars})))'


def _shift_1day_formula(last_row: int) -> str:
    days = f'A3:A{last_row}'
    times = f'B3:B{last_row}'
    return (
        f'=LET(days,{days},t,{times},keys,C3#,vals,F3#,'
        'ud,UNIQUE(days),pos,XMATCH(days,ud),'
        'prev,IF(pos>1,INDEX(ud,pos-1),""),'
        'prevKeys,IF(prev="","",TEXT(prev,"yyyy-mm-dd")&"|"&TEXT(t,"hh:mm:ss")),'
        'IF(prev="","",IFERROR(XLOOKUP(prevKeys,keys,vals,""),"")))'
    )


def _compare_spill_formula(nrows: int) -> str:
    last_row = BACKEND_DATA_START_ROW + nrows - 1
    return (
        f'=LET(rows,SEQUENCE({nrows}),tol,$B${COMPARE_START_ROW - 1},'
        f'time,BACKEND!A{BACKEND_DATA_START_ROW}:A{last_row},'
        f'b10,BACKEND!B{BACKEND_DATA_START_ROW}:B{last_row},x10,PRICE!G3#,'
        'e10b,LEN(b10&"")=0,e10x,LEN(x10&"")=0,'
        'd10,IF(e10b+e10x,"",ABS(b10-x10)),'
        'ok10,IF(e10b*e10x,"EMPTY",IF(e10b+e10x,"MISSING",IF(d10<=tol,"PASS","FAIL"))),'
        f'b5,BACKEND!C{BACKEND_DATA_START_ROW}:C{last_row},x5,PRICE!H3#,'
        'e5b,LEN(b5&"")=0,e5x,LEN(x5&"")=0,'
        'd5,IF(e5b+e5x,"",ABS(b5-x5)),'
        'ok5,IF(e5b*e5x,"EMPTY",IF(e5b+e5x,"MISSING",IF(d5<=tol,"PASS","FAIL"))),'
        f'b1,BACKEND!D{BACKEND_DATA_START_ROW}:D{last_row},x1,PRICE!I3#,'
        'e1b,LEN(b1&"")=0,e1x,LEN(x1&"")=0,'
        'd1,IF(e1b+e1x,"",ABS(b1-x1)),'
        'ok1,IF(e1b*e1x,"EMPTY",IF(e1b+e1x,"MISSING",IF(d1<=tol,"PASS","FAIL"))),'
        'HSTACK(rows,time,b10,x10,d10,ok10,b5,x5,d5,ok5,b1,x1,d1,ok1))'
    )


# ---------------------------------------------------------------------------
# Sheet 1: PRICE
# ---------------------------------------------------------------------------
def _write_price_sheet(ws, trading_days: list, times: list, opens: list, adjs: list, nrows: int, shift_bars: dict[str, int]) -> None:
    _write_remark(ws, 'Price data from test_2a MAIN. '
                       'open_adj = open_price * adj_mul (Excel formula). '
                       'Dynamic-array formulas spill helper and shift columns. '
                       'SHIFT_1DAY matches previous trading_day + same clock time.')

    headers = [
        'trading_day',
        'trade_time',
        'time_key',
        'open_price',
        'adj_mul',
        'open_adj',
        'SHIFT_10MIN',
        'SHIFT_5BAR',
        'SHIFT_1DAY',
    ]
    _write_header(ws, headers)

    last_row = DATA_ROW_OFFSET + nrows
    for i in range(nrows):
        row_cells: list[Any] = [
            _styled_cell(ws, trading_days[i], number_format='yyyy-mm-dd'),
            _styled_cell(ws, times[i], number_format=DT_FMT),
            _price_time_key_formula(last_row) if i == 0 else None,
            _styled_cell(ws, opens[i], number_format=NUM_FMT),
            _styled_cell(ws, adjs[i], number_format=NUM_FMT),
            _open_adjusted_formula(last_row) if i == 0 else None,
        ]
        for name, _shift_val in SHIFTS:
            if name == 'SHIFT_1DAY':
                continue
            row_cells.append(_shift_bars_formula(shift_bars[name]) if i == 0 else None)
        row_cells.append(_shift_1day_formula(last_row) if i == 0 else None)
        ws.append(row_cells)


# ---------------------------------------------------------------------------
# Sheet 2: BACKEND
# ---------------------------------------------------------------------------
def _backend_shift(product: CNFutures, shift_val) -> pd.Series:
    """用后端 ShiftOp 计算 shift，返回 index=signal_time 的 Series。"""
    tester = FactorTester(products=[product], logger_file=False)
    factor = _OpenAdjustedFactor().get_factor(**{'$F': '1min', '$Rev': '0'})
    factor.evaluate([product])

    col_ref = ColumnRef(DataColumn.OPEN_ADJUSTED)
    shift_expr = ShiftOp('shift', ConstExpr(shift_val), col_ref)

    freq = DataFreq('1min')
    ctx = EvaluateContext(products=[product], freq=freq)
    df = shift_expr.evaluate(ctx=ctx)
    return _normalise_series_index(pd.Series(pd.to_numeric(df[product], errors='coerce')))


def _write_backend_sheet(ws, product: CNFutures, times: list) -> dict[str, int]:
    """写后端三种 shift 结果。返回每种 shift 的列号（供 COMPARE 使用，1-based）。"""
    _write_remark(ws, 'Backend ShiftOp(ColumnRef(OPEN_ADJUSTED), N) results.')

    headers = ['trade_time', 'SHIFT_10MIN', 'SHIFT_5BAR', 'SHIFT_1DAY']
    _write_header(ws, headers)

    shift_series: dict[str, pd.Series] = {}
    for sn, sv in SHIFTS:
        try:
            shift_series[sn] = _backend_shift(product, sv)
        except Exception as e:
            print(f'  WARNING: backend shift {sn} failed: {e}')
            shift_series[sn] = pd.Series(dtype=float)

    for i, t in enumerate(times):
        ts = pd.Timestamp(t)
        row_cells: list[Any] = [_styled_cell(ws, t, number_format=DT_FMT)]
        for sn, _ in SHIFTS:
            s = shift_series[sn]
            if ts in s.index:
                val = s.loc[ts]
                row_cells.append(
                    _styled_cell(ws, float(val), number_format=NUM_FMT) if pd.notna(val) else ''
                )
            else:
                row_cells.append('')
        ws.append(row_cells)

    return {'SHIFT_10MIN': 2, 'SHIFT_5BAR': 3, 'SHIFT_1DAY': 4}


# ---------------------------------------------------------------------------
# Sheet 3: COMPARE
# ---------------------------------------------------------------------------
def _write_compare_sheet(ws, nrows: int) -> None:
    _write_remark(ws, 'Compare PRICE excel-shift vs BACKEND python-shift. '
                       'Status: PASS if abs_diff < TOLERANCE, MISSING if one side empty.')

    headers = ['row', 'time',
               'backend_10min', 'excel_10min', 'diff_10min', 'ok_10min',
               'backend_5bar', 'excel_5bar', 'diff_5bar', 'ok_5bar',
               'backend_1day', 'excel_1day', 'diff_1day', 'ok_1day']
    _write_header(ws, headers)

    # 配置行
    ws.append([
        _styled_cell(ws, 'TOLERANCE', fill=HEADER_FILL, font=REMARK_FONT),
        0.0001,
        *([''] * (len(headers) - 2)),
    ])

    ws.append([_compare_spill_formula(nrows)])


# ---------------------------------------------------------------------------
# 主逻辑
# ---------------------------------------------------------------------------
def process_product(prod_code: str) -> Path:
    prod_path = TEST_2A_DIR / f'{prod_code}.xlsx'
    data = _read_test2a_main(prod_path)
    if data is None:
        raise RuntimeError(f'No cached data for {prod_code} in test_2a')
    trading_days, times, opens, adjs = data
    nrows = len(times)

    product = CNFutures(_product_name(prod_code))
    shift_bars = _shift_bars(product)

    TEST_4A_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TEST_4A_DIR / f'{prod_code}.xlsx'

    print(f'  {prod_code} ({product.name}): {nrows} rows, shift bars={shift_bars}', flush=True)
    wb = Workbook(write_only=True)

    price_ws = wb.create_sheet(PRICE_SHEET)
    _write_price_sheet(price_ws, trading_days, times, opens, adjs, nrows, shift_bars)

    backend_ws = wb.create_sheet(BACKEND_SHEET)
    _write_backend_sheet(backend_ws, product, times)

    compare_ws = wb.create_sheet(COMPARE_SHEET)
    _write_compare_sheet(compare_ws, nrows)

    wb.save(out_path)
    _style_workbook(out_path)
    return out_path


def _style_workbook(path: Path) -> None:
    wb = load_workbook(path)
    try:
        for ws in wb.worksheets:
            if ws.max_column > 1:
                ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ws.max_column)
            remark_cell = ws.cell(1, 1)
            remark_cell.fill = REMARK_FILL
            remark_cell.font = COMMENT_FONT
            remark_cell.alignment = Alignment(wrap_text=True, vertical='top')
            ws.column_dimensions['A'].width = 22
            for c in 'BCDEFGHIJKLMN':
                ws.column_dimensions[c].width = 18
    finally:
        wb.save(path)
        wb.close()


def main() -> None:
    parser = argparse.ArgumentParser(description='test_4a: verify ShiftOp')
    parser.add_argument('product_codes', nargs='*', default=['A'],
                        help='Product codes (default: A)')
    args = parser.parse_args()

    for code in args.product_codes:
        try:
            process_product(code)
            print(f'  {code}: OK')
        except Exception as e:
            print(f'  {code}: ERROR - {e}')
            import traceback
            traceback.print_exc()
            sys.exit(1)


def test_shift_workbook_for_a_product():
    out_path = process_product('A')
    wb = load_workbook(out_path, read_only=False, data_only=False)
    try:
        assert wb.sheetnames == [PRICE_SHEET, BACKEND_SHEET, COMPARE_SHEET]
        price_ws = wb[PRICE_SHEET]
        backend_ws = wb[BACKEND_SHEET]
        compare_ws = wb[COMPARE_SHEET]
        assert [str(r) for r in price_ws.merged_cells.ranges] == ['A1:I1']
        assert [str(r) for r in backend_ws.merged_cells.ranges] == ['A1:D1']
        assert [str(r) for r in compare_ws.merged_cells.ranges] == ['A1:N1']
        for ws in (price_ws, backend_ws, compare_ws):
            assert ws['A1'].font.italic is True
            assert ws['A1'].font.bold is False
        assert price_ws.cell(2, 1).value == 'trading_day'
        assert price_ws.cell(2, 2).value == 'trade_time'
        assert price_ws.cell(2, 9).value == 'SHIFT_1DAY'
        assert backend_ws.cell(2, 2).value == 'SHIFT_10MIN'
        assert compare_ws.cell(COMPARE_START_ROW - 1, 1).value == 'TOLERANCE'
        compare_formula = compare_ws.cell(COMPARE_START_ROW, 1).value
        assert isinstance(compare_formula, str)
        assert compare_formula.startswith('=LET(')
        assert 'HSTACK' in compare_formula
        assert backend_ws.cell(BACKEND_DATA_START_ROW + 10, 2).value not in ('', None)
        assert backend_ws.cell(BACKEND_DATA_START_ROW + 5, 3).value not in ('', None)
        shift_1day_formula = price_ws.cell(BACKEND_DATA_START_ROW, 9).value
        assert isinstance(shift_1day_formula, str)
        assert 'UNIQUE' in shift_1day_formula
        assert 'XLOOKUP' in shift_1day_formula
    finally:
        wb.close()


if __name__ == '__main__':
    main()
