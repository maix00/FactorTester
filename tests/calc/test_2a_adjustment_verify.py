"""
test_2a_adjustment_verify.py
-----------------------------
纯 Excel 公式版本 — REDUCE + VSTACK 动态拼接主力连续序列。

整体方案：
1. 从 test_1 复制合约 sheet 数据到 test_2a xlsx（同文件内）。
2. _SWITCHES 用 Excel 公式定位每个主力区间的起止行、复权用收盘价、引用字符串。
   Python 只写原始切换记录和公式文本，不把辅助计算结果写成固定值。
3. MAIN 用一个 REDUCE + VSTACK + HSTACK 动态数组公式拼出完整主力连续序列。
   不用 Python 逐行拼接，也不硬编码合约名、区间行数或合约数量。

🚫 test_1 已经跑好，此脚本不会重新跑 test_1。

_SWITCHES 辅助列（全部 Excel 公式，不硬编码行号、不硬编码 sheet 名）：
  _start_row:  当前合约 start_date 对应的第一条分钟行
  _end_row:    当前合约 end_date 对应的最后一条分钟行
  _data_cols:  合约 sheet row 2 中最后一个非空表头所在列号
  _data_last_col: 合约数据最后一列列字母，用于拼 ref_str
  _close_col:  通过 row 2 表头 MATCH("close_price") 得到 close 列号
  _cur_close:  当前合约 _end_row 的收盘价
  _next_close: 下一合约变成主力前一行的收盘价
  _next_adj:   下一行的 adjustment_mul（向前引用）
  adjustment_mul: =IF(最后一行, 1, _cur_close/_next_close * _next_adj)
      前复权：最新合约=1，历史数据反向累积
  adjustment_add: =0

MAIN!A3 的 VSTACK 语义：
  公式遍历 _SWITCHES!M3:M{last_row} 中的 ref_str。每个 ref_str 形如
  "'a2405'!A123:<last_col>456"，终止列由 Excel 公式根据合约 sheet row 2 的表头数判断。
  对每一段：
    d = INDIRECT(ref) 取得所有原始分钟数据列
    m = EXPAND(该行 adjustment_mul, 该行 _segment_rows, 1, adjustment_mul)
    a = EXPAND(该行 adjustment_add, 该行 _segment_rows, 1, adjustment_add)
    HSTACK(d, m, a) 得到“数据列 + adjustment_mul + adjustment_add”
  REDUCE 从标量 0 开始，把每一段 HSTACK 结果 VSTACK 到 acc 下方，
  最后 DROP(...,1) 去掉初始标量行。这样 MAIN 只有 A3 一个公式，
  但会向右、向下溢出完整连续主力数据。

MAIN!A2 的表头语义：
  表头不由 Python 固定列表写入。A2 用 HSTACK 公式从第一个合约
  sheet 的 row 2 动态读取 A 到 _data_last_col 的原始表头，再追加
  "adjustment_mul" 和 "adjustment_add"。所以合约数据列数变化时，
  MAIN 的表头和 MAIN!A3 的数据宽度保持同一套 Excel 公式语义。

为什么要 XML 后处理：
  openpyxl 能写公式文本，但不会把它标成 Excel/WPS 认可的动态数组公式。
  WPS 打开普通公式时可能自动给其中的引用加 @，把数组语义退化成单值语义。
  因此保存后需要直接修改 sheet XML：给 MAIN!A2/A3 的 <f> 加 t="array"、
  ref="A2:..."/ref="A3:..."、ca="1" 等属性，明确告诉 WPS 这是动态数组溢出公式。

为什么要改 <col style>：
  动态数组的溢出单元格不是 openpyxl 逐格写出的，普通单元格 number_format
  不会自然落到所有溢出行。WPS 对列级 <col style="xfId"> 的继承更稳定，
  所以 XML 后处理会给 MAIN 的日期/时间列写入列样式；A=trading_day 使用
  yyyy-mm-dd，其他从合约 sheet 读取到的日期/时间格式按列复用。

Output: data/test/test_2a/{prod}.xlsx
"""

import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter, column_index_from_string

from tests.calc import (
    TEST_1_DIR, TEST_2A_DIR,
    FORMULA_FILL, HEADER_FILL,
    REMARK_FILL, REMARK_FONT, COMMENT_FONT, COMMENT_ALIGNMENT,
    remark_height,
)
from tests.calc.test_1_export_truncated import validate_test_1_complete

# ============================================================
# XML namespaces
# ============================================================

NS_SHEET = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
NS_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
ET.register_namespace('', NS_SHEET)
ET.register_namespace('r', NS_R)


# ============================================================
# Excel reference helpers
# ============================================================

def _col_letter(idx: int) -> str:
    return get_column_letter(idx)


def _col_idx(ref: str) -> int:
    """从 Excel 引用如 'A3' 或 'AB10' 提取 1-based 列号"""
    import re as _re
    m = _re.match(r'([A-Z]+)', ref)
    if not m:
        return 0
    return column_index_from_string(m.group(1))


# ============================================================
# Workbook layout constants
# ============================================================

# test_1 合约 sheet 布局：row1=remark, row2=header, row3+=data。
# 数据列宽由 Excel 在 _SWITCHES!R:S 判断；这里只保留定位必须固定的行/列。
CONTRACT_TD_COL = 1  # A: trading_day
DATA_START_ROW = 3   # 数据从第3行开始 (1=remark, 2=header)

# _SWITCHES 列定义
# A=trading_day, B=instrument_id, C=windcode, D=start_date, E=end_date
# F=_cur_close, G=_next_close, H=_next_adj, I=adjustment_mul, J=adjustment_add
# K=_segment_rows, L=_ref_rows, M=_ref_str, N=_start_row, O=_end_row
# P=_next_start_row, Q=_next_pre_main_row, R=_data_cols, S=_data_last_col
# T=_close_col, U=_close_col_letter
#
# 前复权 (forward-adjusted)：最新合约 adj=1，历史数据反向累积
#   adjustment_mul[i] = _cur_close[i] / _next_close * _next_adj
#   最后一行=1，向前逐行乘 → 最新价格水平不变，历史数据被压缩
#
# 定位一律使用合约 sheet A 列 trading_day；不要用 B 列 trade_time 推导日期。
# _start_row (N):         Excel 公式 — start_date 在合约 sheet A 列中的第一条分钟行
# _end_row (O):           Excel 公式 — end_date 在合约 sheet A 列中的最后一条分钟行
# _next_pre_main_row (Q): Excel 公式 — 下一合约 start_row - 1
# _segment_rows (K):      Excel 公式 =O3-N3+1 — 主力期间分钟行数
# _ref_rows (L):          Excel 公式 =N3&":"&O3 — 主力期间起止行
# _ref_str (M):           Excel 公式 ="'"&B3&"'!A"&N3&":"&S3&O3 — INDIRECT 引用字符串
# _data_cols (R):         Excel 公式 — 合约 sheet row 2 最后一个非空表头列号
# _data_last_col (S):     Excel 公式 — _data_cols 对应的列字母
# _close_col (T):         Excel 公式 — MATCH("close_price", 合约 sheet row 2)
# _close_col_letter (U):  Excel 公式 — _close_col 对应的列字母
SW_ORIG_COLS = 5
CUR_CLOSE_COL = SW_ORIG_COLS + 1   # F=6: _cur_close (本合约 end_row 收盘)
NEXT_CLOSE_COL = SW_ORIG_COLS + 2  # G=7: _next_close (下一合约主力前一行收盘)
NEXT_ADJ_COL = SW_ORIG_COLS + 3    # H=8: _next_adj (下一合约的 adj_mul)
ADJ_MUL_COL = SW_ORIG_COLS + 4     # I=9: adjustment_mul
ADJ_ADD_COL = SW_ORIG_COLS + 5     # J=10: adjustment_add
SW_SEGMENT_ROWS_COL = SW_ORIG_COLS + 6     # K=11: _segment_rows (Excel公式 =O-N+1)
SW_REF_ROWS_COL = SW_ORIG_COLS + 7         # L=12: _ref_rows (Excel公式)
SW_REF_STR_COL = SW_ORIG_COLS + 8          # M=13: _ref_str (Excel公式)
SW_START_ROW_COL = SW_ORIG_COLS + 9        # N=14: _start_row (Excel公式)
SW_END_ROW_COL = SW_ORIG_COLS + 10         # O=15: _end_row (Excel公式)
SW_NEXT_START_ROW_COL = SW_ORIG_COLS + 11  # P=16: _next_start_row (Excel公式)
SW_NEXT_PRE_ROW_COL = SW_ORIG_COLS + 12    # Q=17: _next_pre_main_row (Excel公式)
SW_DATA_COLS_COL = SW_ORIG_COLS + 13       # R=18: _data_cols (Excel公式)
SW_DATA_LAST_COL_COL = SW_ORIG_COLS + 14   # S=19: _data_last_col (Excel公式)
SW_CLOSE_COL_COL = SW_ORIG_COLS + 15       # T=20: _close_col (Excel公式)
SW_CLOSE_LETTER_COL = SW_ORIG_COLS + 16    # U=21: _close_col_letter (Excel公式)


# ============================================================
# Input workbook helpers
# ============================================================

def _check_sheets_match(src_path: Path, dst_path: Path) -> bool:
    """Check if dst has the same contract sheets (name/row count) as src.
    Returns True if sheets match → can do in-place update without re-copying."""
    if not dst_path.exists():
        return False
    try:
        src_wb = load_workbook(src_path, read_only=True)
        dst_wb = load_workbook(dst_path, read_only=True)
        src_ct = {sn for sn in src_wb.sheetnames if sn != '_SWITCHES'}
        dst_ct = {sn for sn in dst_wb.sheetnames if sn not in ('_SWITCHES', 'MAIN')}
        if src_ct != dst_ct:
            src_wb.close()
            dst_wb.close()
            return False
        for sn in src_ct:
            src_rows = src_wb[sn].max_row
            dst_rows = dst_wb[sn].max_row
            if src_rows != dst_rows:
                src_wb.close()
                dst_wb.close()
                return False
        src_wb.close()
        dst_wb.close()
        return True
    except Exception:
        return False


def _date_key(value) -> str:
    if hasattr(value, 'date'):
        return value.date().isoformat()
    return str(value)[:10]


def _segment_row_count(ws, start_date, end_date) -> int:
    start_key = _date_key(start_date)
    end_key = _date_key(end_date)
    start_row = None
    end_row = None
    for row in range(DATA_START_ROW, ws.max_row + 1):
        value = ws.cell(row, CONTRACT_TD_COL).value
        if value is None:
            continue
        key = _date_key(value)
        if start_row is None and key == start_key:
            start_row = row
        if key == end_key:
            end_row = row
    if start_row is None or end_row is None or end_row < start_row:
        return 0
    return end_row - start_row + 1


# ============================================================
# Product workbook generation
# ============================================================

def process_product(prod_xlsx: Path) -> None:
    prod = prod_xlsx.stem
    src_path = TEST_1_DIR / f'{prod}.xlsx'
    if not src_path.exists():
        print(f"  ⚠️ test_1 file not found: {src_path.name}, skipping")
        return

    dst_path = TEST_2A_DIR / f'{prod}.xlsx'
    inplace = _check_sheets_match(src_path, dst_path)

    print(f"  Processing: {prod}..." + (" (in-place)" if inplace else ""), end='', flush=True)

    # ============================================================
    # 1. 读取 test_1 源文件结构
    # ============================================================
    src_wb = load_workbook(src_path, read_only=True)
    src_sheets_set = {sn for sn in src_wb.sheetnames if sn != '_SWITCHES'}

    # 每个合约 sheet 的数据行数
    sheet_rows = {}
    for sn in sorted(src_sheets_set):
        ws = src_wb[sn]
        n = ws.max_row - 2
        if n > 0:
            sheet_rows[sn] = n

    # 读取 _SWITCHES 中的切换列表
    sw_ws = src_wb['_SWITCHES']
    sw_header_row = 2
    sw_data_start = 3

    td_col = None
    inst_col = None
    wc_col = None
    sd_col = None
    ed_col = None
    for c in range(1, sw_ws.max_column + 1):
        v = sw_ws.cell(sw_header_row, c).value
        if v == 'trading_day':
            td_col = c
        elif v == 'instrument_id':
            inst_col = c
        elif v == 'windcode':
            wc_col = c
        elif v == 'start_date':
            sd_col = c
        elif v == 'end_date':
            ed_col = c

    if td_col is None or inst_col is None:
        print(f"  ⚠️ Cannot find _SWITCHES columns, skipping {prod}")
        src_wb.close()
        return

    switches = []
    for row in range(sw_data_start, sw_ws.max_row + 1):
        td = sw_ws.cell(row, td_col).value
        inst = sw_ws.cell(row, inst_col).value
        if td and inst:
            wc = sw_ws.cell(row, wc_col).value if wc_col else None
            sd = sw_ws.cell(row, sd_col).value if sd_col else None
            ed = sw_ws.cell(row, ed_col).value if ed_col else None
            # Keep original types (datetime, not str!) for Excel MATCH compatibility
            switches.append((str(inst), td, wc, sd, ed))

    if not switches:
        print(f"  ⚠️ No switches found for {prod}, skipping")
        src_wb.close()
        return

    # ============================================================
    # 2. 创建或打开输出 workbook
    # ============================================================
    if inplace:
        # Incremental: open existing file, update _SWITCHES + MAIN only
        src_wb.close()
        wb = load_workbook(dst_path)
        # Remove old _SWITCHES and MAIN sheets (re-create with fresh formulas)
        for sn in ('_SWITCHES', 'MAIN'):
            if sn in wb.sheetnames:
                del wb[sn]
        sheet_rows = {}
        for sn in wb.sheetnames:
            n = wb[sn].max_row - 2
            if n > 0:
                sheet_rows[sn] = n
    else:
        # Full: create new workbook, copy contract sheets from test_1
        sheet_rows = {}
        for sn in sorted(src_sheets_set):
            n = src_wb[sn].max_row - 2
            if n > 0:
                sheet_rows[sn] = n

        wb = Workbook()
        active_sheet = wb.active
        if active_sheet is not None:
            wb.remove(active_sheet)

        # 2a. 复制合约 sheet 数据（从 test_1 直接 copy values, 再补样式）
        for sn in sorted(src_sheets_set):
            dst_ws = wb.create_sheet(sn)
            src_ct = src_wb[sn]
            for row_data in src_ct.iter_rows(values_only=True):
                dst_ws.append(list(row_data))
            # 补样式：row1 remark + row2 header（与 test_1 一致）
            ncols = dst_ws.max_column
            dst_ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
            r1 = dst_ws.cell(1, 1)
            r1.fill = REMARK_FILL
            r1.font = COMMENT_FONT
            r1.alignment = COMMENT_ALIGNMENT
            remark_text = str(r1.value) if r1.value is not None else ' '
            dst_ws.row_dimensions[1].height = remark_height(remark_text)
            for ci in range(1, ncols + 1):
                c = dst_ws.cell(2, ci)
                c.fill = HEADER_FILL
                c.font = REMARK_FONT
        src_wb.close()

    max_data_cols = max(
        (wb[sn].max_column for sn in wb.sheetnames if sn not in ('_SWITCHES', 'MAIN')),
        default=21,
    )
    main_ncols = max_data_cols + 2

    # ----------------------------------------------------------
    # Sheet 0: _SWITCHES (增强版 — 辅助列计算 adjust_mul)
    # ----------------------------------------------------------
    sw_out = wb.create_sheet('_SWITCHES', 0)

    # Row 1: remark (合并单元格 + 自动换行)
    sw_remark = (
        '切换记录 + 前复权因子计算（最新合约=1，历史数据反向累积）\n'
        '辅助列全部为 Excel 公式，不硬编码合约 sheet 行号\n'
        '_start_row: MATCH(start_date)，取主力区间起始交易日第一条分钟行\n'
        '_end_row: LOOKUP(end_date)，取主力区间终止交易日最后一条分钟行\n'
        '_next_pre_main_row: 下一合约 start_row - 1，即新合约变成主力前一行\n'
        '_cur_close:  INDEX(本合约 close, _end_row)\n'
        '_next_close: INDEX(下一合约 close, _next_pre_main_row)\n'
        '_data_cols/_data_last_col: 根据合约 sheet row 2 表头自动判断数据列宽\n'
        '_segment_rows: =_end_row-_start_row+1；_ref_rows: =_start_row&_end_row；_ref_str: 主力区间引用\n'
        'adj_mul: IF(最后一行,1, _cur_close/_next_close * _next_adj)'
    )
    sw_out.cell(1, 1, sw_remark)
    sw_out.merge_cells(start_row=1, start_column=1, end_row=1, end_column=21)
    sw_out.row_dimensions[1].height = remark_height(sw_remark)
    sw_cell1 = sw_out.cell(1, 1)
    sw_cell1.fill = REMARK_FILL
    sw_cell1.font = COMMENT_FONT
    sw_cell1.alignment = COMMENT_ALIGNMENT

    # Row 2: header
    headers = ['trading_day', 'instrument_id', 'windcode', 'start_date', 'end_date',
               '_cur_close', '_next_close', '_next_adj', 'adjustment_mul', 'adjustment_add',
               '_segment_rows', '_ref_rows', '_ref_str', '_start_row', '_end_row',
               '_next_start_row', '_next_pre_main_row', '_data_cols', '_data_last_col',
               '_close_col', '_close_col_letter']
    for ci, h in enumerate(headers, 1):
        c = sw_out.cell(2, ci, h)
        c.fill = HEADER_FILL
        c.font = REMARK_FONT

    # ---- 写入切换数据 + 公式 ----
    contracts_in_order = [s[0] for s in switches]
    sw_last_row = 2 + len(switches)

    for i, (inst, td, wc, sd, ed) in enumerate(switches):
        row = i + 3  # Excel row (1=remark, 2=header)

        # 基本数据 — 保持原始类型（datetime 不转 str，Excel MATCH 才能匹配）
        sw_out.cell(row, 1, td)
        sw_out.cell(row, 2, inst)
        sw_out.cell(row, 3, wc)
        sw_out.cell(row, 4, sd)
        sw_out.cell(row, 5, ed)

        cur_b = f'{_col_letter(2)}{row}'    # B: instrument_id 本行
        cur_d = f'{_col_letter(4)}{row}'    # D: start_date 本行
        cur_e = f'{_col_letter(5)}{row}'    # E: end_date 本行
        cur_td_ref = f'INDIRECT("\'"&{cur_b}&"\'!A:A")'
        cur_header_ref = f'INDIRECT("\'"&{cur_b}&"\'!2:2")'
        last_row_formula = f'ROW()={sw_last_row}'

        # ---- data width / close column helpers（全部 Excel 公式）----
        sw_out.cell(
            row, SW_DATA_COLS_COL,
            f'=LOOKUP(2,1/({cur_header_ref}<>""),COLUMN({cur_header_ref}))'
        ).fill = FORMULA_FILL
        sw_out.cell(
            row, SW_DATA_LAST_COL_COL,
            f'=SUBSTITUTE(ADDRESS(1,{_col_letter(SW_DATA_COLS_COL)}{row},4),"1","")'
        ).fill = FORMULA_FILL
        sw_out.cell(
            row, SW_CLOSE_COL_COL,
            f'=MATCH("close_price",{cur_header_ref},0)'
        ).fill = FORMULA_FILL
        sw_out.cell(
            row, SW_CLOSE_LETTER_COL,
            f'=SUBSTITUTE(ADDRESS(1,{_col_letter(SW_CLOSE_COL_COL)}{row},4),"1","")'
        ).fill = FORMULA_FILL

        # ---- _start_row / _end_row / next helper rows（全部 Excel 公式）----
        # 定位一律使用合约 sheet A 列 trading_day。
        # start_row = start_date 当天第一条分钟行；end_row = end_date 当天最后一条分钟行。
        sw_out.cell(
            row, SW_START_ROW_COL,
            f'=MATCH({cur_d},{cur_td_ref},0)'
        ).fill = FORMULA_FILL
        sw_out.cell(
            row, SW_END_ROW_COL,
            f'=LOOKUP(2,1/({cur_td_ref}={cur_e}),ROW({cur_td_ref}))'
        ).fill = FORMULA_FILL

        if i == len(switches) - 1:
            next_start_formula = f'=IF({last_row_formula},"","")'
            next_pre_formula = f'=IF({last_row_formula},"","")'
        else:
            next_b = f'{_col_letter(2)}{row + 1}'
            next_d = f'{_col_letter(4)}{row + 1}'
            next_td_ref = f'INDIRECT("\'"&{next_b}&"\'!A:A")'
            next_start_formula = (
                f'=IF({last_row_formula},"",MATCH({next_d},{next_td_ref},0))'
            )
            next_pre_formula = (
                f'=IF({last_row_formula},"",{_col_letter(SW_NEXT_START_ROW_COL)}{row}-1)'
            )
        sw_out.cell(row, SW_NEXT_START_ROW_COL, next_start_formula).fill = FORMULA_FILL
        sw_out.cell(row, SW_NEXT_PRE_ROW_COL, next_pre_formula).fill = FORMULA_FILL

        # ---- _cur_close / _next_close ----
        # 当前合约取主力区间终止行 close；下一合约取变成主力前一行 close。
        cur_close_ref = (
            f'INDIRECT("\'"&{cur_b}&"\'!"&{_col_letter(SW_CLOSE_LETTER_COL)}{row}'
            f'&":"&{_col_letter(SW_CLOSE_LETTER_COL)}{row})'
        )
        sw_out.cell(
            row, CUR_CLOSE_COL,
            f'=INDEX({cur_close_ref},{_col_letter(SW_END_ROW_COL)}{row})'
        ).fill = FORMULA_FILL
        if i == len(switches) - 1:
            next_close_formula = f'=IF({last_row_formula},"","")'
        else:
            next_b = f'{_col_letter(2)}{row + 1}'
            next_close_ref = (
                f'INDIRECT("\'"&{next_b}&"\'!"&{_col_letter(SW_CLOSE_LETTER_COL)}{row + 1}'
                f'&":"&{_col_letter(SW_CLOSE_LETTER_COL)}{row + 1})'
            )
            next_close_formula = (
                f'=IF({last_row_formula},"",INDEX({next_close_ref},'
                f'{_col_letter(SW_NEXT_PRE_ROW_COL)}{row}))'
            )
        sw_out.cell(row, NEXT_CLOSE_COL, next_close_formula).fill = FORMULA_FILL

        # ---- _next_adj / adjustment_mul / adjustment_add ----
        sw_out.cell(
            row, NEXT_ADJ_COL,
            f'=IF({last_row_formula},"",{_col_letter(ADJ_MUL_COL)}{row + 1})'
        ).fill = FORMULA_FILL
        cc = _col_letter(CUR_CLOSE_COL)
        nc = _col_letter(NEXT_CLOSE_COL)
        na = _col_letter(NEXT_ADJ_COL)
        sw_out.cell(
            row, ADJ_MUL_COL,
            f'=IF({last_row_formula},1,IF(OR({cc}{row}="",{nc}{row}="",{na}{row}=""),"",'
            f'{cc}{row}/{nc}{row}*{na}{row}))'
        ).fill = FORMULA_FILL
        sw_out.cell(row, ADJ_ADD_COL, '=0').fill = FORMULA_FILL

        # ---- segment rows / ref rows / ref string ----
        sw_out.cell(
            row, SW_SEGMENT_ROWS_COL,
            f'={_col_letter(SW_END_ROW_COL)}{row}-{_col_letter(SW_START_ROW_COL)}{row}+1'
        ).fill = FORMULA_FILL
        sw_out.cell(
            row, SW_REF_ROWS_COL,
            f'={_col_letter(SW_START_ROW_COL)}{row}&":"&{_col_letter(SW_END_ROW_COL)}{row}'
        ).fill = FORMULA_FILL
        sw_out.cell(
            row, SW_REF_STR_COL,
            f'="\'"&{cur_b}&"\'!A"&{_col_letter(SW_START_ROW_COL)}{row}'
            f'&":"&{_col_letter(SW_DATA_LAST_COL_COL)}{row}&{_col_letter(SW_END_ROW_COL)}{row}'
        ).fill = FORMULA_FILL

    # ----------------------------------------------------------
    # Sheet 2: MAIN (单公式 REDUCE+HSTACK+VSTACK — 13列数据+mul+add，无硬编码)
    # ----------------------------------------------------------
    # 核心洞察：
    #   1. REDUCE 初始值为标量 0，LAMBDA 内 VSTACK(acc, HSTACK(data, mul, add))
    #   2. HSTACK 在 VSTACK 的 LAMBDA 内没溢出问题（因为标量 init）
    #   3. DROP(,1) 去掉初始标量行
    # 公式无需知道合约数量，自动遍历 _SWITCHES!M3:M{N}
    main_ws = wb.create_sheet('MAIN', 1)

    sw_last_col_letter = _col_letter(SW_REF_STR_COL)  # M

    # Row 1: remark (合并单元格 + 自动换行)
    main_remark = (
        f'主力连续序列 — REDUCE+HSTACK+VSTACK 单公式 (数据列+2列复权因子)\n'
        f'合约数 = {len(switches)}，公式不硬编码合约数量或数据列数\n'
        f'A3 = DROP(REDUCE(0, _SWITCHES!M3:M{sw_last_row}, LAMBDA(acc,ref, ...)), 1)'
    )
    main_ws.cell(1, 1, main_remark)
    main_ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=main_ncols)
    main_ws.row_dimensions[1].height = remark_height(main_remark)
    main_cell1 = main_ws.cell(1, 1)
    main_cell1.fill = REMARK_FILL
    main_cell1.font = COMMENT_FONT
    main_cell1.alignment = COMMENT_ALIGNMENT

    # Row 2: header formula (原始数据表头 + adjustment_mul + adjustment_add)
    header_formula = (
        '=HSTACK('
        'INDIRECT("\'"&INDEX(_SWITCHES!B:B,3)&"\'!A2:"&INDEX(_SWITCHES!S:S,3)&"2"),'
        '"adjustment_mul","adjustment_add")'
    )
    c = main_ws.cell(2, 1, header_formula)
    c.fill = HEADER_FILL
    c.font = REMARK_FONT

    # --- A3: 单公式溢出 数据列+2 列 ---
    # REDUCE VSTACK 拼接各合约 HSTACK(数据列, mul, add)，DROP 去掉初始标量
    # 一式溢出所有数据列+2列，日期格式由 XML <col style> 后处理控制
    #   <col style="xfDate"> → A/B/R 列溢出区域显示日期格式
    #   A3 的 s= 匹配第一列(A列=trading_day)的日期格式
    base_formula = (
        f'REDUCE(0,_SWITCHES!{sw_last_col_letter}3:{sw_last_col_letter}{sw_last_row},'
        f'LAMBDA(acc,ref,'
        f'LET(r,ROW(ref),'
        f'd,INDIRECT(ref),'
        f'm,EXPAND(INDEX(_SWITCHES!I:I,r),INDEX(_SWITCHES!K:K,r),1,INDEX(_SWITCHES!I:I,r)),'
        f'a,EXPAND(INDEX(_SWITCHES!J:J,r),INDEX(_SWITCHES!K:K,r),1,INDEX(_SWITCHES!J:J,r)),'
        f'VSTACK(acc,HSTACK(d,m,a))'
        f')))'
    )
    main_ws.cell(3, 1, f'=DROP({base_formula},1)').fill = FORMULA_FILL

    total_rows = 0
    for inst, _td, _wc, sd, ed in switches:
        if inst in wb.sheetnames:
            total_rows += _segment_row_count(wb[inst], sd, ed)
    if total_rows == 0:
        total_rows = sum(sheet_rows.get(c, 0) for c in contracts_in_order)

    # ============================================================
    # 3. 保存（不预写单元格格式——用 XML <col style> 后处理）
    # ============================================================
    dst_path = TEST_2A_DIR / f'{prod}.xlsx'
    wb.save(dst_path)
    wb.close()

    # ============================================================
    # 4. XML 后处理：标记动态数组 + 公式 s= + <col style>
    #    <col style> 作用于溢出行（WPS 已验证有效）
    #    公式单元格 s= 作用于公式行（覆盖 <col style>）
    # ============================================================
    last_row = 2 + total_rows
    col_numfmts = _read_contract_col_numfmts_from_xml(dst_path)
    # 注入 <cols> + 修改 MAIN!A2/A3 的 s= + 标记每个为动态数组
    _patch_multi_col_formulas(dst_path, 'MAIN', col_numfmts, total_rows, main_ncols)

    print(f' ✅ ({total_rows} rows, {len(switches)} contracts, {len(contracts_in_order)} in MAIN)')


# ============================================================
# XML style and dynamic-array patching
# ============================================================

def _read_contract_col_numfmts_from_xml(xlsx_path: Path) -> dict[int, int]:
    """
    从已保存的 xlsx 的 XML 层面读取合约 sheet 的列级 numFmtId。

    遍历样式表 styles.xml 的 cellXfs，找到合约数据行 cell 的 s=，
    映射到 numFmtId。
    """
    import zipfile as _zf
    with _zf.ZipFile(xlsx_path, 'r') as zf:
        # 解析 styles.xml
        styles = ET.parse(zf.open('xl/styles.xml'))
        styles_root = styles.getroot()
        cellXfs = styles_root.find(f'{{{NS_SHEET}}}cellXfs')
        if cellXfs is None:
            return {}
        xf_list = cellXfs.findall(f'{{{NS_SHEET}}}xf')
        numFmts = styles_root.find(f'{{{NS_SHEET}}}numFmts')

        # 找到合约 sheet（非 _SWITCHES, 非 MAIN）
        wb_xml = ET.parse(zf.open('xl/workbook.xml'))
        for sh in wb_xml.getroot().findall(f'{{{NS_SHEET}}}sheets/{{{NS_SHEET}}}sheet'):
            sn = sh.get('name')
            if sn in ('_SWITCHES', 'MAIN'):
                continue
            # 找这个 sheet 文件
            r_id = sh.get(f'{{{NS_R}}}id')
            rels_xml = ET.parse(zf.open('xl/_rels/workbook.xml.rels'))
            target = None
            for rel in rels_xml.getroot():
                if rel.get('Id') == r_id:
                    t = rel.get('Target')
                    if t is not None:
                        target = t.lstrip('/')
                    break
            if target is None:
                continue

            sheet = ET.parse(zf.open(target))
            s_root = sheet.getroot()
            # 找 row 3
            result = {}
            for row in s_root.findall(f'{{{NS_SHEET}}}sheetData/{{{NS_SHEET}}}row'):
                if row.get('r') == '3':
                    for c in row.findall(f'{{{NS_SHEET}}}c'):
                        r = c.get('r')
                        if r is None:
                            continue
                        s = c.get('s')
                        if s is None:
                            continue
                        si = int(s)
                        if si < len(xf_list):
                            nfi = xf_list[si].get('numFmtId')
                            if nfi is not None and nfi != '0':
                                # 找到列号
                                col_idx = _col_idx(r)
                                result[col_idx] = int(nfi)
                    break
            return result
    return {}


def _patch_multi_col_formulas(xlsx_path: Path, sheet_name: str,
                              col_numfmts: dict[int, int],
                              total_data_rows: int,
                              main_ncols: int):
    """
    XML 后处理：给 MAIN sheet 的 A3 标记为单公式动态数组，
    设置正确的 <col style> 让溢出行继承日期格式。

    关键：styles.xml 里注入 yyyy-mm-dd 纯日期 numFmt，
    A 列 <col style> 指向它（而非 datetime 格式）。
    """
    _DATE_FMT = 'yyyy\\-mm\\-dd'

    all_files: dict[str, bytes] = {}
    with zipfile.ZipFile(xlsx_path, 'r') as zf:
        # --- 1. 解析 styles.xml，注入纯日期 numFmt + cellXfs ---
        styles_str = zf.read('xl/styles.xml')
        styles_root = ET.fromstring(styles_str)
        numFmts = styles_root.find(f'{{{NS_SHEET}}}numFmts')
        if numFmts is None:
            numFmts = ET.SubElement(styles_root, f'{{{NS_SHEET}}}numFmts')

        # 找最大 numFmtId
        max_nfi = 163
        for nf in numFmts.findall(f'{{{NS_SHEET}}}numFmt'):
            nfi = int(nf.get('numFmtId', '0'))
            if nfi > max_nfi:
                max_nfi = nfi

        # 检查是否已有 yyyy-mm-dd
        date_nfi = None
        for nf in numFmts.findall(f'{{{NS_SHEET}}}numFmt'):
            if nf.get('formatCode') == _DATE_FMT:
                date_nfi = int(nf.get('numFmtId', '0'))
                break

        if date_nfi is None:
            date_nfi = max_nfi + 1
            date_el = ET.SubElement(numFmts, f'{{{NS_SHEET}}}numFmt')
            date_el.set('numFmtId', str(date_nfi))
            date_el.set('formatCode', _DATE_FMT)

            # 注入对应 cellXfs（复制 xf 0，只改 numFmtId）
            cellXfs = styles_root.find(f'{{{NS_SHEET}}}cellXfs')
            if cellXfs is not None:
                xf_list = cellXfs.findall(f'{{{NS_SHEET}}}xf')
                if xf_list:
                    # 复制第一个 xf（通常是默认格式）
                    base_xf = xf_list[0]
                    new_xf = ET.SubElement(cellXfs, f'{{{NS_SHEET}}}xf')
                    for ak in ('fontId', 'fillId', 'borderId', 'xfId', 'applyNumberFormat'):
                        v = base_xf.get(ak)
                        if v is not None:
                            new_xf.set(ak, v)
                    new_xf.set('numFmtId', str(date_nfi))
                    new_xf.set('applyNumberFormat', '1')

                    # 更新 cellXfs count
                    old_count = int(cellXfs.get('count', '0'))
                    cellXfs.set('count', str(old_count + 1))

        # --- 2. 重新解析 styles（含新注入的 xf）--- 
        styles_root2 = ET.fromstring(ET.tostring(styles_root, encoding='unicode'))
        xf_list = styles_root2.findall(f'{{{NS_SHEET}}}cellXfs/{{{NS_SHEET}}}xf')
        nfi_to_xf: dict[int, int] = {}
        for i, xf in enumerate(xf_list):
            nfi = xf.get('numFmtId')
            if nfi is not None:
                nfi_to_xf[int(nfi)] = i

        date_xf_id = nfi_to_xf.get(date_nfi, 0)

        # --- 3. 找 sheet 文件 ---
        wb_xml = ET.parse(zf.open('xl/workbook.xml'))
        rel_target = None
        for sh in wb_xml.getroot().findall(f'{{{NS_SHEET}}}sheets/{{{NS_SHEET}}}sheet'):
            if sh.get('name') == sheet_name:
                r_id = sh.get(f'{{{NS_R}}}id')
                rels = ET.parse(zf.open('xl/_rels/workbook.xml.rels'))
                for rel in rels.getroot():
                    if rel.get('Id') == r_id:
                        t = rel.get('Target')
                        if t is not None:
                            rel_target = t.lstrip('/')
                        break
                break

        if rel_target is None:
            print(f'  ⚠️ Sheet "{sheet_name}" not found')
            return

        sheet = ET.parse(zf.open(rel_target))
        sheet_root = sheet.getroot()

        # --- 4. 注入 <cols> ---
        #    A=trading_day 用纯日期 yyyy-mm-dd；其他日期列保持时间格式
        cols = sheet_root.find(f'{{{NS_SHEET}}}cols')
        if cols is not None:
            sheet_root.remove(cols)
        cols_el = ET.Element(f'{{{NS_SHEET}}}cols')
        for ci in range(1, main_ncols + 1):
            col_el = ET.SubElement(cols_el, f'{{{NS_SHEET}}}col')
            col_el.set('min', str(ci))
            col_el.set('max', str(ci))
            col_el.set('width', '13')
            col_el.set('customWidth', '1')
            if ci in (1,):  # A=trading_day: 纯日期
                col_el.set('style', str(date_xf_id))
            elif ci in col_numfmts:
                xf_id = nfi_to_xf.get(col_numfmts[ci])
                if xf_id is not None:
                    col_el.set('style', str(xf_id))
        sheet_root.insert(0, cols_el)

        # --- 5. A2/A3 单公式动态数组 ---
        last_row = 2 + total_data_rows
        safe_ref_end = last_row + 1
        last_col_letter = _col_letter(main_ncols)

        for row in sheet_root.findall(f'{{{NS_SHEET}}}sheetData/{{{NS_SHEET}}}row'):
            row_ref = row.get('r')
            if row_ref not in ('2', '3'):
                continue
            for c in row.findall(f'{{{NS_SHEET}}}c'):
                cell_ref = c.get('r')
                if cell_ref not in ('A2', 'A3'):
                    continue
                f_el = c.find(f'{{{NS_SHEET}}}f')
                if f_el is not None:
                    f_el.set('ca', '1')
                    f_el.set('t', 'array')
                    f_el.set(
                        'ref',
                        f'A2:{last_col_letter}2' if cell_ref == 'A2'
                        else f'A3:{last_col_letter}{safe_ref_end}',
                    )
                    c.set('cm', '1')
                if cell_ref == 'A3':
                    c.set('s', str(date_xf_id))

        # --- 6. 收集并重写（含修改后的 styles.xml）---
        all_files = {}
        for name in zf.namelist():
            if name in ('xl/styles.xml', rel_target):
                continue
            all_files[name] = zf.read(name)
        all_files['xl/styles.xml'] = ET.tostring(styles_root2, xml_declaration=True, encoding='UTF-8')
        all_files[rel_target] = ET.tostring(sheet_root, xml_declaration=True, encoding='UTF-8')

    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.xlsx')
    os.close(tmp_fd)
    try:
        with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zf_out:
            for name, data in all_files.items():
                zf_out.writestr(name, data)
        shutil.move(tmp_path, str(xlsx_path))
    finally:
        if Path(tmp_path).exists():
            Path(tmp_path).unlink(missing_ok=True)

    print(
        f'  🔧 Patched MAIN!A2/A3: dynamic arrays A2:{last_col_letter}2 '
        f'and A3:{last_col_letter}{safe_ref_end} + col styles'
    )


# ============================================================
# Entrypoint
# ============================================================

def main():
    print("test_2a: Excel-formula adjustment verification (INDEX/MATCH, in-file)")
    print("=" * 60)
    print("\n⛔ Note: test_1 data is NOT re-run.")
    print("   Contract data copied from test_1 (no INDIRECT cross-file refs)")
    print(f"   Source: {TEST_1_DIR}")
    print(f"   Output: {TEST_2A_DIR}")

    complete, problems = validate_test_1_complete()
    if not complete:
        print("\n⛔ test_1 data is incomplete; test_2a will not continue.")
        for problem in problems:
            print(f"   - {problem}")
        return

    # 确保输出目录存在（不清空，支持增量更新）
    TEST_2A_DIR.mkdir(parents=True, exist_ok=True)

    # 🔧 DEBUG: 只跑 A.xlsx
    xlsx_path = TEST_1_DIR / 'A.xlsx'
    if xlsx_path.exists():
        process_product(xlsx_path)

    print(f"\nDone! Output: {TEST_2A_DIR}")


if __name__ == '__main__':
    main()
