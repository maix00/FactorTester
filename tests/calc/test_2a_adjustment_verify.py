"""
test_2a_adjustment_verify.py
-----------------------------
纯 Excel 公式版本：
1. 复制 _SWITCHES sheet，添加辅助列用公式计算 adjust_mul
2. 在 MAIN sheet 用公式引用 test_1 合约数据，VLOOKUP _SWITCHES 的 adjust_mul

🚫 test_1 已经跑好，此脚本不会重新跑 test_1。

_SWITCHES 增强逻辑（全部 Excel 公式）：
  辅助列：
    _prev_close: INDIRECT 引用 test_1 前一合约 sheet 中切换日最后一条的 close
    _cur_close:  INDIRECT 引用 test_1 当前合约 sheet 中切换日第一天的 close
    _prev_adj:   上一行的 adjust_mul（累乘基准）
    adjust_mul:  =IF(第一行, 1, _prev_close/_cur_close * _prev_adj)
    adjust_add:  =0

MAIN sheet：
  用 INDIRECT 从 test_1 合约 sheet 按行号引用数据
  用 VLOOKUP 或 INDEX/MATCH 从本文件 _SWITCHES 查 adjust_mul/add

数据源：仅 test_1 的 xlsx + Excel 公式。

Output: data/test/test_2a/{prod}.xlsx
"""

import shutil
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
CONTRACT_COLS = [
    'trade_time', 'trading_day', 'instrument_id',
    'open_price', 'highest_price', 'lowest_price', 'close_price', 'settlement_price',
    'volume', 'turnover', 'open_interest',
]
CONTRACT_CLOSE_COL = 7  # close_price

# test_1 合约 sheet 数据起始行
DATA_START_ROW = 3


def process_product(prod_xlsx: Path) -> None:
    prod = prod_xlsx.stem
    src_path = TEST_1_DIR / f'{prod}.xlsx'
    if not src_path.exists():
        print(f"  ⚠️ test_1 file not found: {src_path.name}, skipping")
        return

    print(f"  Processing: {prod}...", end='', flush=True)

    # ============================================================
    # 1. 读取 test_1 源文件结构
    # ============================================================
    src_wb = load_workbook(src_path, data_only=True, read_only=True)
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
    # _SWITCHES 列布局: col1=remark, col2=header row
    # 实际数据: A=trading_day, B=instrument_id, C=windcode, D=start_date, E=end_date
    # 但 remark 行可能打乱了列。用 header row 定位。
    sw_header_row = 2
    sw_data_start = 3

    # 找到所有需要的列：trading_day, instrument_id, windcode, start_date, end_date
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
            switches.append((str(inst), td, wc, sd, ed))  # (instrument_id, trading_day, windcode, start_date, end_date)

    src_wb.close()

    if not switches:
        print(f"  ⚠️ No switches found for {prod}, skipping")
        return

    # ============================================================
    # 2. 创建输出 workbook
    # ============================================================
    wb = Workbook()
    wb.remove(wb.active)

    # 相对路径：test_2a/A.xlsx → ../test_1/A.xlsx
    rel_path = f'../test_1/{prod}.xlsx'

    # ----------------------------------------------------------
    # Sheet 0: _SWITCHES (增强版 — 辅助列计算 adjust_mul)
    # ----------------------------------------------------------
    sw_out = wb.create_sheet('_SWITCHES', 0)

    # Row 1: remark
    sw_out.cell(
        1, 1,
        f'切换记录 + 复权因子计算（引用自 {rel_path}）\n'
        f'辅助列公式全部为 Excel 函数，无硬编码值\n'
        f'prev_close/cur_close = INDIRECT从test_1合约sheet查切换日前一交易日收盘价\n'
        f'adj_mul = IF(第一行, 1, prev_close/cur_close * 上一行adj_mul)'
    )

    # 确定列布局
    # 原列: A=trading_day, B=instrument_id, C=windcode, D=start_date, E=end_date
    # 辅助列: F=prev_close, G=cur_close, H=_prev_adj, I=adj_mul, J=adj_add
    SW_ORIG_COLS = 5  # 原 _SWITCHES 有 5 列
    PREV_CLOSE_COL = SW_ORIG_COLS + 1  # F
    CUR_CLOSE_COL = SW_ORIG_COLS + 2   # G
    PREV_ADJ_COL = SW_ORIG_COLS + 3    # H
    ADJ_MUL_COL = SW_ORIG_COLS + 4     # I
    ADJ_ADD_COL = SW_ORIG_COLS + 5     # J

    # Row 2: header
    sw_out.cell(2, 1, 'trading_day').fill = HEADER_FILL
    sw_out.cell(2, 2, 'instrument_id').fill = HEADER_FILL
    sw_out.cell(2, 3, 'windcode').fill = HEADER_FILL
    sw_out.cell(2, 4, 'start_date').fill = HEADER_FILL
    sw_out.cell(2, 5, 'end_date').fill = HEADER_FILL
    sw_out.cell(2, PREV_CLOSE_COL, '_prev_close').fill = HEADER_FILL
    sw_out.cell(2, CUR_CLOSE_COL, '_cur_close').fill = HEADER_FILL
    sw_out.cell(2, PREV_ADJ_COL, '_prev_adj').fill = HEADER_FILL
    sw_out.cell(2, ADJ_MUL_COL, 'adjustment_mul').fill = HEADER_FILL
    sw_out.cell(2, ADJ_ADD_COL, 'adjustment_add').fill = HEADER_FILL

    # 写入切换数据 + 公式
    prev_inst_to_last_row = {}  # 记录前一个合约 sheet 的数据最后行号
    for i, (inst, td, wc, sd, ed) in enumerate(switches):
        row = i + 3  # Excel row (1=remark, 2=header)

        # 基本数据
        sw_out.cell(row, 1, td)
        sw_out.cell(row, 2, inst)
        sw_out.cell(row, 3, wc)
        sw_out.cell(row, 4, sd)
        sw_out.cell(row, 5, ed)

        if i > 0:
            prev_inst = switches[i - 1][0]
        else:
            prev_inst = None

        # ---- _prev_close: 前一个合约 sheet 最后一行的 close ----
        # =INDIRECT("'" & rel_path & "'!" & prev_inst & "!G" & prev_last_row)
        if prev_inst and prev_inst in sheet_rows:
            last_row = DATA_START_ROW + sheet_rows[prev_inst] - 1
            prev_ref = f"'{rel_path}'!{prev_inst}!${_col_letter(CONTRACT_CLOSE_COL)}${last_row}"
            sw_out.cell(row, PREV_CLOSE_COL, f'=INDIRECT("{prev_ref}")').fill = FORMULA_FILL

        # ---- _cur_close: 当前合约 sheet 第一行的 close ----
        # =INDIRECT("'" & rel_path & "'!" & inst & "!G3")
        if inst in sheet_rows:
            cur_ref = f"'{rel_path}'!{inst}!${_col_letter(CONTRACT_CLOSE_COL)}${DATA_START_ROW}"
            sw_out.cell(row, CUR_CLOSE_COL, f'=INDIRECT("{cur_ref}")').fill = FORMULA_FILL

        # ---- _prev_adj: 上一行的 adjust_mul ----
        if i == 0:
            sw_out.cell(row, PREV_ADJ_COL, 1).fill = FORMULA_FILL
        else:
            sw_out.cell(
                row, PREV_ADJ_COL,
                f'={_col_letter(ADJ_MUL_COL)}{row - 1}'
            ).fill = FORMULA_FILL

        # ---- adjust_mul ----
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

        # ---- adjust_add ----
        sw_out.cell(row, ADJ_ADD_COL, 0).fill = FORMULA_FILL

    # ----------------------------------------------------------
    # Sheet 1: MAIN (主力连续序列)
    # ----------------------------------------------------------
    main_ws = wb.create_sheet('MAIN', 1)

    # MAIN 列布局:
    #   A: _contract (辅助-合约名)
    #   B..L: 数据列 (同 CONTRACT_COLS, 11列)
    #   M: adjustment_mul (VLOOKUP _SWITCHES)
    #   N: adjustment_add

    MAIN_CONTRACT_COL = 1
    MAIN_DATA_START = 2
    MAIN_MUL_COL = MAIN_DATA_START + len(CONTRACT_COLS)      # M = 13
    MAIN_ADD_COL = MAIN_DATA_START + len(CONTRACT_COLS) + 1  # N = 14

    # Row 1: remark
    main_ws.cell(
        1, 1,
        f'主力连续序列（引用自 {rel_path}）\n'
        f'数据列用 INDIRECT 从 test_1 合约 sheet 按行号引用\n'
        f'adjustment_mul/add 用 VLOOKUP 从本文件 _SWITCHES 查询'
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

            # 数据列：INDIRECT 从 test_1 合约 sheet 引用
            for ci in range(len(CONTRACT_COLS)):
                src_col = ci + 1
                col = MAIN_DATA_START + ci
                ref = f"'{rel_path}'!{contract_name}!${_col_letter(src_col)}${src_row}"
                main_ws.cell(row, col, f'=INDIRECT("{ref}")')

            # adjustment_mul: VLOOKUP 从 _SWITCHES
            # =VLOOKUP(_contract, _SWITCHES!B:I, 8, FALSE)
            # _SWITCHES: B=instrument_id(2), I=adjust_mul(9)
            contract_cell = _col_letter(MAIN_CONTRACT_COL) + str(row)
            mul_formula = (
                f'=VLOOKUP({contract_cell},'
                f'_SWITCHES!$B${DATA_START_ROW}:${_col_letter(ADJ_MUL_COL)}${2 + len(switches)},'
                f'{ADJ_MUL_COL - 1},FALSE)'
            )
            main_ws.cell(row, MAIN_MUL_COL, mul_formula).fill = FORMULA_FILL

            # adjustment_add: VLOOKUP _SWITCHES
            add_formula = (
                f'=VLOOKUP({contract_cell},'
                f'_SWITCHES!$B${DATA_START_ROW}:${_col_letter(ADJ_ADD_COL)}${2 + len(switches)},'
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
    print("test_2a: Excel-formula adjustment verification (INDIRECT + VLOOKUP)")
    print("=" * 60)
    print("\n⛔ Note: test_1 data is NOT re-run. All data = Excel INDIRECT refs.")
    print(f"   Source: {TEST_1_DIR}")
    print(f"   Output: {TEST_2A_DIR}")

    # 清空 TEST_2A_DIR
    if TEST_2A_DIR.exists():
        for item in TEST_2A_DIR.iterdir():
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            except Exception as e:
                print(f"  ⚠️ Failed to remove {item}: {e}")
    else:
        TEST_2A_DIR.mkdir(parents=True, exist_ok=True)

    # 🔧 DEBUG: 只跑 A.xlsx
    xlsx_path = TEST_1_DIR / 'A.xlsx'
    if xlsx_path.exists():
        process_product(xlsx_path)

    print(f"\nDone! Output: {TEST_2A_DIR}")


if __name__ == '__main__':
    main()
