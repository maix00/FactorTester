"""
test_2a_adjustment_verify.py
-----------------------------
纯 Excel 公式版本 — REDUCE + VSTACK 动态拼接主力连续序列。

方案：
1. 从 test_1 复制合约 sheet 数据到 test_2a xlsx（同文件内）
2. _SWITCHES 用 INDIRECT 动态引用合约 sheet（不硬编码 sheet 名）
3. MAIN 用 REDUCE+VSTACK+INDIRECT 数组公式自动拼接所有合约数据行
   — 不需要 Python for 循环逐行写，不硬编码合约名或行号

🚫 test_1 已经跑好，此脚本不会重新跑 test_1。

_SWITCHES 辅助列（全部 Excel 公式，不硬编码行号、不硬编码 sheet 名）：
  _prev_close: =INDEX(INDIRECT("'"&上一行B&"'!G:G"), MATCH(上一行E, INDIRECT("'"&上一行B&"'!B:B"), 0))
      通过上一行 instrument_id (B列) 动态获取前合约 sheet 名，不硬编码
  _cur_close:  =INDEX(INDIRECT("'"&本行B&"'!G:G"), MATCH(本行D, INDIRECT("'"&本行B&"'!B:B"), 0))
      通过本行 instrument_id (B列) 动态获取本合约 sheet 名，不硬编码
  _prev_adj:   上一行的 adjustment_mul
  adjustment_mul: =IF(第一行, 1, _prev_close/_cur_close * _prev_adj)
  adjustment_add: =0

MAIN sheet（VSTACK 展平 + INDIRECT，A3 溢出）：
  每个合约一个 HSTACK 参数 = HSTACK(DROP(INDIRECT(_SWITCHES!L{n}),2), EXPAND(...), EXPAND(...))
  合约名/行号由 _SWITCHES L 列（_ref_str）动态提供，不硬编码
  VSTACK 参数数 = 合约数（Python for 循环生成，写入 xlsx）

Output: data/test/test_2a/{prod}.xlsx
"""

from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter

from tests.calc import TEST_1_DIR, TEST_2A_DIR

# --- 样式 ---
FORMULA_FILL = PatternFill(start_color='FFFFF2CC', end_color='FFFFF2CC', fill_type='solid')
HEADER_FILL = PatternFill(start_color='FFD9E1F2', end_color='FFD9E1F2', fill_type='solid')


def _col_letter(idx: int) -> str:
    return get_column_letter(idx)


# test_1 合约 sheet 列布局 (row1=remark, row2=header, row3+=data)
# A=trade_time, B=trading_day, C=instrument_id, D=open_price, E=highest_price,
# F=lowest_price, G=close_price, H=settlement_price, I=volume, J=turnover, K=open_interest
CONTRACT_COLS = [
    'trade_time', 'trading_day', 'instrument_id',
    'open_price', 'highest_price', 'lowest_price', 'close_price', 'settlement_price',
    'volume', 'turnover', 'open_interest',
]
CONTRACT_CLOSE_COL = 7      # G: close_price
CONTRACT_TD_COL = 2          # B: trading_day
DATA_START_ROW = 3           # 数据从第3行开始 (1=remark, 2=header)

# _SWITCHES 列定义
# A=trading_day, B=instrument_id, C=windcode, D=start_date, E=end_date
# F=_prev_close, G=_cur_close, H=_prev_adj, I=adjustment_mul, J=adjustment_add
# K=_nrows（该合约数据行数，纯数值）
# L=_ref_str（INDIRECT 引用字符串，Excel 公式拼接，如 'a2405'!A3:K14027）
SW_ORIG_COLS = 5
PREV_CLOSE_COL = SW_ORIG_COLS + 1  # F=6
CUR_CLOSE_COL = SW_ORIG_COLS + 2   # G=7
PREV_ADJ_COL = SW_ORIG_COLS + 3    # H=8
ADJ_MUL_COL = SW_ORIG_COLS + 4     # I=9
ADJ_ADD_COL = SW_ORIG_COLS + 5     # J=10
SW_NROWS_COL = SW_ORIG_COLS + 6    # K=11: _nrows
SW_REF_STR_COL = SW_ORIG_COLS + 7  # L=12: _ref_str

# MAIN 列布局 (11 数据列 + 2 adjustment 列 = 13 列, A..M)
# A..K = 合约数据, L=adjustment_mul, M=adjustment_add
MAIN_NCOLS = len(CONTRACT_COLS) + 2  # 13
MAIN_MUL_COL_OFFSET = len(CONTRACT_COLS) + 1  # L=12 (在 13 列中的位置)
MAIN_ADD_COL_OFFSET = len(CONTRACT_COLS) + 2  # M=13


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
        wb.remove(wb.active)

        # 2a. 复制合约 sheet 数据（从 test_1 直接 copy values）
        for sn in sorted(src_sheets_set):
            dst_ws = wb.create_sheet(sn)
            src_ct = src_wb[sn]
            for row_data in src_ct.iter_rows(values_only=True):
                dst_ws.append(list(row_data))
        src_wb.close()

    # ----------------------------------------------------------
    # Sheet 0: _SWITCHES (增强版 — 辅助列计算 adjust_mul)
    # ----------------------------------------------------------
    sw_out = wb.create_sheet('_SWITCHES', 0)

    # Row 1: remark
    sw_out.cell(
        1, 1,
        '切换记录 + 复权因子计算\n'
        '辅助列公式全部为 Excel 函数，不硬编码行号\n'
        '_prev_close: INDEX(前合约!G:G, MATCH(end_date, 前合约!B:B, 0))\n'
        '_cur_close:  INDEX(本合约!G:G, MATCH(start_date, 本合约!B:B, 0))\n'
        'adj_mul: IF(第一行,1, _prev_close/_cur_close * _prev_adj)'
    )

    # Row 2: header
    headers = ['trading_day', 'instrument_id', 'windcode', 'start_date', 'end_date',
               '_prev_close', '_cur_close', '_prev_adj', 'adjustment_mul', 'adjustment_add',
               '_nrows', '_ref_str']
    for ci, h in enumerate(headers, 1):
        sw_out.cell(2, ci, h).fill = HEADER_FILL

    # ---- 写入切换数据 + 公式 ----
    contracts_in_order = [s[0] for s in switches]

    for i, (inst, td, wc, sd, ed) in enumerate(switches):
        row = i + 3  # Excel row (1=remark, 2=header)

        # 基本数据 — 保持原始类型（datetime 不转 str，Excel MATCH 才能匹配）
        sw_out.cell(row, 1, td)
        sw_out.cell(row, 2, inst)
        sw_out.cell(row, 3, wc)
        sw_out.cell(row, 4, sd)
        sw_out.cell(row, 5, ed)

        # ---- _prev_close ----
        # =INDEX(INDIRECT("'"&上一行B&"'!G:G"), MATCH(上一行E, INDIRECT("'"&上一行B&"'!B:B"), 0))
        # 不硬编码 sheet 名：通过上一行 instrument_id (B列) 动态获取前合约 sheet 名
        if i == 0:
            sw_out.cell(row, PREV_CLOSE_COL, '').fill = FORMULA_FILL
        elif i > 0:
            prev_b = f'{_col_letter(2)}{row - 1}'   # B: instrument_id 上一行
            prev_e = f'{_col_letter(5)}{row - 1}'   # E: end_date 上一行
            prev_g_ref = f'INDIRECT("\'"&{prev_b}&"\'!G:G")'
            prev_b_ref = f'INDIRECT("\'"&{prev_b}&"\'!B:B")'
            formula = f'=INDEX({prev_g_ref},MATCH({prev_e},{prev_b_ref},0))'
            sw_out.cell(row, PREV_CLOSE_COL, formula).fill = FORMULA_FILL

        # ---- _cur_close ----
        # =INDEX(INDIRECT("'"&本行B&"'!G:G"), MATCH(本行D, INDIRECT("'"&本行B&"'!B:B"), 0))
        cur_b = f'{_col_letter(2)}{row}'    # B: instrument_id 本行
        cur_d = f'{_col_letter(4)}{row}'    # D: start_date 本行
        cur_g_ref = f'INDIRECT("\'"&{cur_b}&"\'!G:G")'
        cur_b_ref = f'INDIRECT("\'"&{cur_b}&"\'!B:B")'
        formula = f'=INDEX({cur_g_ref},MATCH({cur_d},{cur_b_ref},0))'
        sw_out.cell(row, CUR_CLOSE_COL, formula).fill = FORMULA_FILL

        # ---- _prev_adj: 上一行的 adjustment_mul ----
        if i == 0:
            sw_out.cell(row, PREV_ADJ_COL, 1).fill = FORMULA_FILL
        else:
            sw_out.cell(
                row, PREV_ADJ_COL,
                f'={_col_letter(ADJ_MUL_COL)}{row - 1}'
            ).fill = FORMULA_FILL

        # ---- adjustment_mul ----
        if i == 0:
            sw_out.cell(row, ADJ_MUL_COL, 1).fill = FORMULA_FILL
        else:
            pc = _col_letter(PREV_CLOSE_COL)
            cc = _col_letter(CUR_CLOSE_COL)
            pa = _col_letter(PREV_ADJ_COL)
            sw_out.cell(
                row, ADJ_MUL_COL,
                f'=IF({pc}{row}="","",IF({cc}{row}="","",{pc}{row}/{cc}{row}*{pa}{row}))'
            ).fill = FORMULA_FILL

        # ---- adjustment_add ----
        sw_out.cell(row, ADJ_ADD_COL, 0).fill = FORMULA_FILL

        # ---- _nrows（纯数值，供 MAIN REDUCE 数组公式使用）----
        sw_out.cell(row, SW_NROWS_COL, sheet_rows.get(inst, 0))

        # ---- _ref_str（Excel 公式拼接引用字符串，如 'a2405'!A3:K14027）----
        # ="'"&B{row}&"'!A3:K"&K{row}+2
        ref_formula = (
            f'="\'"&{_col_letter(2)}{row}&"\'!A3:K"&'
            f'{_col_letter(SW_NROWS_COL)}{row}+2'
        )
        sw_out.cell(row, SW_REF_STR_COL, ref_formula).fill = FORMULA_FILL

    # ----------------------------------------------------------
    # Sheet 1: MAIN (主力连续序列 — REDUCE + INDIRECT 动态拼接)
    # ----------------------------------------------------------
    main_ws = wb.create_sheet('MAIN', 1)

    sw_last_row = 2 + len(switches)

    # Row 1: remark
    main_ws.cell(
        1, 1,
        '主力连续序列 — VSTACK + INDIRECT 动态拼接\n'
        '每个合约 = HSTACK(DROP(INDIRECT(_SWITCHES!L{{n}}),2), EXPAND(_SWITCHES!I{{n}},...))\n'
        '合约名/行号由 _SWITCHES 辅助列动态提供，不硬编码\n'
        '合约数 = ROWS(_SWITCHES!L3:L{})'.format(sw_last_row)
    )

    # Row 2: header (11 数据列 + 2 adjustment 列)
    for ci, cn in enumerate(CONTRACT_COLS):
        main_ws.cell(2, ci + 1, cn).fill = HEADER_FILL
    main_ws.cell(2, MAIN_MUL_COL_OFFSET, 'adjustment_mul').fill = HEADER_FILL
    main_ws.cell(2, MAIN_ADD_COL_OFFSET, 'adjustment_add').fill = HEADER_FILL

    # A3: VSTACK 展平 — 每个合约一个 HSTACK 参数，通过 _SWITCHES! 引用
    # HSTACK(
    #   DROP(INDIRECT(_SWITCHES!L{n}), 2),
    #   EXPAND(_SWITCHES!I{n}, _SWITCHES!K{n}, 1, _SWITCHES!I{n}),
    #   EXPAND(_SWITCHES!J{n}, _SWITCHES!K{n}, 1, _SWITCHES!J{n})
    # )
    # 所有 sheet/行号引用都通过 _SWITCHES! 动态获取
    vstack_parts = []
    for i in range(len(switches)):
        row = i + 3
        part = (
            f'HSTACK('
            f'DROP(INDIRECT(_SWITCHES!L{row}),2),'
            f'EXPAND(_SWITCHES!I{row},_SWITCHES!K{row},1,_SWITCHES!I{row}),'
            f'EXPAND(_SWITCHES!J{row},_SWITCHES!K{row},1,_SWITCHES!J{row})'
            f')'
        )
        vstack_parts.append(part)

    formula = '=VSTACK(' + ','.join(vstack_parts) + ')'
    main_ws.cell(3, 1, formula).fill = FORMULA_FILL

    contracts_in_order = [s[0] for s in switches]
    total_rows = sum(sheet_rows.get(c, 0) for c in contracts_in_order)

    # ============================================================
    # 3. 保存
    # ============================================================
    dst_path = TEST_2A_DIR / f'{prod}.xlsx'
    wb.save(dst_path)
    print(f' ✅ ({total_rows} rows, {len(switches)} contracts, {len(contracts_in_order)} in MAIN)')


def main():
    print("test_2a: Excel-formula adjustment verification (INDEX/MATCH, in-file)")
    print("=" * 60)
    print("\n⛔ Note: test_1 data is NOT re-run.")
    print("   Contract data copied from test_1 (no INDIRECT cross-file refs)")
    print(f"   Source: {TEST_1_DIR}")
    print(f"   Output: {TEST_2A_DIR}")

    # 确保输出目录存在（不清空，支持增量更新）
    TEST_2A_DIR.mkdir(parents=True, exist_ok=True)

    # 🔧 DEBUG: 只跑 A.xlsx
    xlsx_path = TEST_1_DIR / 'A.xlsx'
    if xlsx_path.exists():
        process_product(xlsx_path)

    print(f"\nDone! Output: {TEST_2A_DIR}")


if __name__ == '__main__':
    main()
