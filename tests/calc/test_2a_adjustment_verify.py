"""
test_2a_adjustment_verify.py
-----------------------------
纯 Excel 公式版本 (INDEX/MATCH, 同文件内引用)。

方案：
1. 从 test_1 复制合约 sheet 数据到 test_2a xlsx（同文件内，避免 INDIRECT #REF!）
2. _SWITCHES 辅助列用 INDEX/MATCH 动态查找 close（不硬编码行号）
3. MAIN sheet 直接 =合约sheet!$col$row 引用，VLOOKUP 查 _SWITCHES

🚫 test_1 已经跑好，此脚本不会重新跑 test_1。

_SWITCHES 辅助列（全部 Excel 公式，不硬编码行号）：
  _prev_close: =INDEX(prev_inst!G:G, MATCH(end_date, prev_inst!B:B, 0))
      从切换日列表的end_date在前一合约sheet的trading_day列中匹配，取close
  _cur_close:  =INDEX(cur_inst!G:G, MATCH(start_date, cur_inst!B:B, 0))
      从切换日列表的start_date在当前合约sheet的trading_day列中匹配，取close
  _prev_adj:   上一行的 adjustment_mul
  adjustment_mul: =IF(第一行, 1, _prev_close/_cur_close * _prev_adj)
  adjustment_add: =0

MAIN sheet：
  直接 =合约sheet!$col$row 引用（同文件内，不需要 INDIRECT）
  VLOOKUP 从本文件 _SWITCHES 查 adjustment_mul/add

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

# _SWITCHES 列定义（复制后的）
# A=trading_day, B=instrument_id, C=windcode, D=start_date, E=end_date
# F=_prev_close, G=_cur_close, H=_prev_adj, I=adjustment_mul, J=adjustment_add
SW_ORIG_COLS = 5
PREV_CLOSE_COL = SW_ORIG_COLS + 1  # F=6
CUR_CLOSE_COL = SW_ORIG_COLS + 2   # G=7
PREV_ADJ_COL = SW_ORIG_COLS + 3    # H=8
ADJ_MUL_COL = SW_ORIG_COLS + 4     # I=9
ADJ_ADD_COL = SW_ORIG_COLS + 5     # J=10

# MAIN 列布局
# A=_contract, B..L=数据, M=adjustment_mul, N=adjustment_add
MAIN_CONTRACT_COL = 1
MAIN_DATA_START = 2
MAIN_MUL_COL = MAIN_DATA_START + len(CONTRACT_COLS)      # M=13
MAIN_ADD_COL = MAIN_DATA_START + len(CONTRACT_COLS) + 1  # N=14


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
               '_prev_close', '_cur_close', '_prev_adj', 'adjustment_mul', 'adjustment_add']
    for ci, h in enumerate(headers, 1):
        sw_out.cell(2, ci, h).fill = HEADER_FILL

    # ---- 写入切换数据 + 公式 ----
    for i, (inst, td, wc, sd, ed) in enumerate(switches):
        row = i + 3  # Excel row (1=remark, 2=header)

        # 基本数据 — 保持原始类型（datetime 不转 str，Excel MATCH 才能匹配）
        sw_out.cell(row, 1, td)
        sw_out.cell(row, 2, inst)
        sw_out.cell(row, 3, wc)
        sw_out.cell(row, 4, sd)
        sw_out.cell(row, 5, ed)

        # ---- _prev_close ----
        # =INDEX(前一合约!G:G, MATCH(本行end_date, 前一合约!B:B, 0))
        # 注：B=trading_day(2), G=close_price(7)
        # end_date 在 E{row}
        if i == 0:
            # 第一个合约：没有前一合约，留空
            sw_out.cell(row, PREV_CLOSE_COL, '').fill = FORMULA_FILL
        elif i > 0:
            prev_inst = switches[i - 1][0]
            # 用 end_date(前一行的 E) 在前一合约 sheet 的 trading_day(B) 列 MATCH
            end_cell = f'{_col_letter(5)}{row - 1}'  # E: end_date 是前一行的
            formula = (
                f'=INDEX(\'{prev_inst}\'!G:G,'
                f'MATCH({end_cell},\'{prev_inst}\'!B:B,0))'
            )
            sw_out.cell(row, PREV_CLOSE_COL, formula).fill = FORMULA_FILL

        # ---- _cur_close ----
        # =INDEX(本合约!G:G, MATCH(本行start_date, 本合约!B:B, 0))
        sd_cell = f'{_col_letter(4)}{row}'  # D: start_date
        formula = (
            f'=INDEX(\'{inst}\'!G:G,'
            f'MATCH({sd_cell},\'{inst}\'!B:B,0))'
        )
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

    # ----------------------------------------------------------
    # Sheet 1: MAIN (主力连续序列)
    # ----------------------------------------------------------
    main_ws = wb.create_sheet('MAIN', 1)

    # Row 1: remark
    main_ws.cell(
        1, 1,
        '主力连续序列（全部 Excel 公式）\n'
        '数据列: =合约sheet!$col$row（同文件内引用，无硬编码行号）\n'
        'adjustment_mul/add: VLOOKUP 从 _SWITCHES 查询'
    )

    # Row 2: header
    main_ws.cell(2, MAIN_CONTRACT_COL, '_contract').fill = HEADER_FILL
    for ci, cn in enumerate(CONTRACT_COLS):
        main_ws.cell(2, MAIN_DATA_START + ci, cn).fill = HEADER_FILL
    main_ws.cell(2, MAIN_MUL_COL, 'adjustment_mul').fill = HEADER_FILL
    main_ws.cell(2, MAIN_ADD_COL, 'adjustment_add').fill = HEADER_FILL

    # 写入 MAIN 数据行
    current_row = 3
    contracts_in_order = [s[0] for s in switches]

    for contract_name in contracts_in_order:
        if contract_name not in sheet_rows:
            continue
        nrows = sheet_rows[contract_name]

        for i in range(nrows):
            src_row = DATA_START_ROW + i
            row = current_row + i

            # _contract 辅助列
            main_ws.cell(row, MAIN_CONTRACT_COL, contract_name).fill = FORMULA_FILL

            # 数据列：直接引用同文件内的合约 sheet
            # =合约sheet!$col$row
            for ci in range(len(CONTRACT_COLS)):
                src_col = ci + 1
                col = MAIN_DATA_START + ci
                ref = f"='{contract_name}'!${_col_letter(src_col)}${src_row}"
                main_ws.cell(row, col, ref).fill = FORMULA_FILL

            # adjustment_mul: VLOOKUP 从 _SWITCHES
            # =VLOOKUP(_contract, _SWITCHES!$B$3:$I$x, 8, FALSE)
            # B=instrument_id, I=adjustment_mul → col_index=8 (I是第9列，B到I共8列)
            contract_cell = _col_letter(MAIN_CONTRACT_COL) + str(row)
            sw_last_row = 2 + len(switches)
            mul_formula = (
                f'=VLOOKUP({contract_cell},'
                f'_SWITCHES!$B${DATA_START_ROW}:${_col_letter(ADJ_MUL_COL)}${sw_last_row},'
                f'{ADJ_MUL_COL - 1},FALSE)'
            )
            main_ws.cell(row, MAIN_MUL_COL, mul_formula).fill = FORMULA_FILL

            # adjustment_add: VLOOKUP _SWITCHES
            add_formula = (
                f'=VLOOKUP({contract_cell},'
                f'_SWITCHES!$B${DATA_START_ROW}:${_col_letter(ADJ_ADD_COL)}${sw_last_row},'
                f'{ADJ_ADD_COL - 1},FALSE)'
            )
            main_ws.cell(row, MAIN_ADD_COL, add_formula).fill = FORMULA_FILL

        current_row += nrows

    total_rows = current_row - 3

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
