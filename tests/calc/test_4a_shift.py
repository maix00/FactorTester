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
        _styled_cell(ws, text, fill=REMARK_FILL, font=REMARK_FONT,
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


# ---------------------------------------------------------------------------
# Sheet 1: PRICE
# ---------------------------------------------------------------------------
def _write_price_sheet(ws, trading_days: list, times: list, opens: list, adjs: list, nrows: int, shift_bars: dict[str, int]) -> None:
    _write_remark(ws, 'Price data from test_2a MAIN. '
                       'open_adj = open_price * adj_mul (Excel formula). '
                       'SHIFT_10MIN / SHIFT_5BAR use bar OFFSET; SHIFT_1DAY matches previous trading_day + same clock time.')

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

    for i in range(nrows):
        row_num = i + DATA_ROW_OFFSET + 1
        # 基础三列
        row_cells = [
            _styled_cell(ws, trading_days[i], number_format='yyyy-mm-dd'),
            _styled_cell(ws, times[i], number_format=DT_FMT),
            f'=TEXT(A{row_num},"yyyy-mm-dd")&"|"&TEXT(B{row_num},"hh:mm:ss")',
            _styled_cell(ws, opens[i], number_format=NUM_FMT),
            _styled_cell(ws, adjs[i], number_format=NUM_FMT),
            f'=D{row_num}*E{row_num}',  # open_adj
        ]
        # 10min / 5bar 使用 bar shift（F 列 = open_adj）。
        for name, _shift_val in SHIFTS:
            if name == 'SHIFT_1DAY':
                continue
            n_bars = shift_bars[name]
            if i >= n_bars:
                row_cells.append(f'=OFFSET($F${row_num},-{n_bars},0)')
            else:
                row_cells.append('')
        # 1day 使用上一交易日 + 同一时钟时间，不假设每天固定 bar 数或自然日连续。
        if row_num == DATA_ROW_OFFSET + 1:
            row_cells.append('')
        else:
            prev_trading_day = f'LOOKUP(2,1/($A$3:A{row_num - 1}<A{row_num}),$A$3:A{row_num - 1})'
            prev_day_key = f'TEXT({prev_trading_day},"yyyy-mm-dd")&"|"&TEXT(B{row_num},"hh:mm:ss")'
            row_cells.append(f'=IFERROR(XLOOKUP({prev_day_key},$C:$C,$F:$F,""),"")')
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
        row_cells = [_styled_cell(ws, t, number_format=DT_FMT)]
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
        0.0001, '', '', '', '',
        '', '', '', '', '',
        '', '', '', '',
    ])

    # PRICE excel shift 列映射：G=SHIFT_10MIN, H=SHIFT_5BAR, I=SHIFT_1DAY
    # BACKEND 列：B=SHIFT_10MIN, C=SHIFT_5BAR, D=SHIFT_1DAY
    for i in range(nrows):
        row_num = COMPARE_START_ROW + i
        row_idx = i + 1  # 1-based row index
        bk_base = BACKEND_DATA_START_ROW  # 3

        cells = [
            row_idx,  # simple row number
            _styled_cell(ws, f'=INDEX(BACKEND!A:A,{bk_base - 1 + row_idx})', number_format=DT_FMT),
            # 10min
            f'=IFERROR(INDEX(BACKEND!B:B,{bk_base - 1 + row_idx}),"")',
            f'=INDEX(PRICE!G:G,{DATA_ROW_OFFSET + row_idx})',
            f'=IF(OR(C{row_num}="",D{row_num}=""),"",ABS(C{row_num}-D{row_num}))',
            f'=IF(AND(C{row_num}="",D{row_num}=""),"EMPTY",IF(OR(C{row_num}="",D{row_num}=""),"MISSING",IF(E{row_num}<=$B${COMPARE_START_ROW-1},"PASS","FAIL")))',
            # 5bar
            f'=IFERROR(INDEX(BACKEND!C:C,{bk_base - 1 + row_idx}),"")',
            f'=INDEX(PRICE!H:H,{DATA_ROW_OFFSET + row_idx})',
            f'=IF(OR(G{row_num}="",H{row_num}=""),"",ABS(G{row_num}-H{row_num}))',
            f'=IF(AND(G{row_num}="",H{row_num}=""),"EMPTY",IF(OR(G{row_num}="",H{row_num}=""),"MISSING",IF(I{row_num}<=$B${COMPARE_START_ROW-1},"PASS","FAIL")))',
            # 1day
            f'=IFERROR(INDEX(BACKEND!D:D,{bk_base - 1 + row_idx}),"")',
            f'=INDEX(PRICE!I:I,{DATA_ROW_OFFSET + row_idx})',
            f'=IF(OR(K{row_num}="",L{row_num}=""),"",ABS(K{row_num}-L{row_num}))',
            f'=IF(AND(K{row_num}="",L{row_num}=""),"EMPTY",IF(OR(K{row_num}="",L{row_num}=""),"MISSING",IF(M{row_num}<=$B${COMPARE_START_ROW-1},"PASS","FAIL")))',
        ]
        ws.append(cells)


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
    wb = load_workbook(out_path, read_only=True, data_only=False)
    try:
        assert wb.sheetnames == [PRICE_SHEET, BACKEND_SHEET, COMPARE_SHEET]
        price_ws = wb[PRICE_SHEET]
        backend_ws = wb[BACKEND_SHEET]
        compare_ws = wb[COMPARE_SHEET]
        assert price_ws.cell(2, 1).value == 'trading_day'
        assert price_ws.cell(2, 2).value == 'trade_time'
        assert price_ws.cell(2, 9).value == 'SHIFT_1DAY'
        assert backend_ws.cell(2, 2).value == 'SHIFT_10MIN'
        assert compare_ws.cell(COMPARE_START_ROW - 1, 1).value == 'TOLERANCE'
        assert compare_ws.cell(COMPARE_START_ROW, 4).value == f'=INDEX(PRICE!G:G,{DATA_ROW_OFFSET + 1})'
        assert backend_ws.cell(BACKEND_DATA_START_ROW + 10, 2).value not in ('', None)
        assert backend_ws.cell(BACKEND_DATA_START_ROW + 5, 3).value not in ('', None)
        assert 'XLOOKUP' in price_ws.cell(BACKEND_DATA_START_ROW + 345, 9).value
    finally:
        wb.close()


if __name__ == '__main__':
    main()
