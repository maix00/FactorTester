"""
test_2a_adjustment_verify.py
-----------------------------
从 test_1 的 Excel 复制，添加前复权因子及 Excel 公式计算。

🚫 test_1 已经跑好，此脚本不会重新跑 test_1。

对每个品种的 test_1 Excel：
1. 清空 TEST_2A_DIR，从 TEST_1_DIR 复制 xlsx 到 TEST_2A_DIR
2. 在每个合约 sheet 中写入 adjust_mul / adjust_add / adj_* 列
   - adjust_mul/add 用 Excel VLOOKUP 从 MAIN sheet 查询
   - adj_price 用公式 =price * adjust_mul + adjust_add
3. 在 index=0 插入 MAIN sheet：按时间合并所有合约数据，生成主力连续序列
   - adjust_mul 用 Excel 公式：切换日 = 上一合约close / 当前合约close * 上一行adjust_mul
   - adjust_add = 0（纯 Excel 公式）

数据源：仅 test_1 的 xlsx 文件。

Output: data/test/test_2a/{prod}.xlsx
"""

import shutil
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter

from tests.calc import TEST_1_DIR, TEST_2A_DIR

# --- 样式 ---
FORMULA_FILL = PatternFill(start_color='FFFFF2CC', end_color='FFFFF2CC', fill_type='solid')
HEADER_FILL = PatternFill(start_color='FFD9E1F2', end_color='FFD9E1F2', fill_type='solid')

# 价格列名（test_1 导出使用的列名）
PRICE_COLS = ['open_price', 'highest_price', 'lowest_price', 'close_price', 'settlement_price']

# _SWITCHES sheet 中的关键列
SW_COL_TRADING_DAY = 'trading_day'
SW_COL_INSTRUMENT_ID = 'instrument_id'

# 合约 sheet 中的关键列
CS_COL_TRADE_TIME = 'trade_time'
CS_COL_INSTRUMENT_ID = 'instrument_id'
CS_COL_CLOSE = 'close_price'
CS_COL_OPEN = 'open_price'
CS_COL_HIGH = 'highest_price'
CS_COL_LOW = 'lowest_price'

# MAIN sheet 列定义（与 test_1 导出列对齐）
MAIN_COLS = [
    'trade_time', 'trading_day', 'instrument_id',
    'open_price', 'highest_price', 'lowest_price', 'close_price', 'settlement_price',
    'volume', 'turnover', 'open_interest',
    'adjustment_mul', 'adjustment_add',
]

# ------------------------------------------------------------
# 工具函数
# ------------------------------------------------------------

def _find_col_idx(headers: list[str | None], col_name: str) -> int | None:
    """在 header 列表中找列索引（1-based）。"""
    for i, h in enumerate(headers, 1):
        if h == col_name:
            return i
    return None


def _col_letter(idx: int) -> str:
    """Convert 1-based column index to Excel column letter(s)."""
    return get_column_letter(idx)


def _clear_and_copy() -> None:
    """清空 TEST_2A_DIR，从 TEST_1_DIR 复制所有 xlsx 到 TEST_2A_DIR。"""
    if TEST_2A_DIR.exists():
        for item in TEST_2A_DIR.iterdir():
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                    print(f"  Removed dir: {item.name}")
                else:
                    item.unlink()
                    print(f"  Removed file: {item.name}")
            except Exception as e:
                print(f"  ⚠️ Failed to remove {item}: {e}")
    else:
        TEST_2A_DIR.mkdir(parents=True, exist_ok=True)

    copied = 0
    for src in sorted(TEST_1_DIR.glob('*.xlsx')):
        dst = TEST_2A_DIR / src.name
        shutil.copy2(src, dst)
        copied += 1

    print(f"\n📋 Copied {copied} .xlsx files from test_1 → test_2a")


# ------------------------------------------------------------
# 3. 在每个合约 sheet 中写入 Excel 公式
# ------------------------------------------------------------

def _add_formulas_to_contract_sheets(wb, main_ws_name: str, main_data_start_row: int) -> None:
    """
    为每个合约 sheet 添加 adjust_mul/adjust_add 列 + adj_price 公式列。

    adjust_mul / adjust_add 用 VLOOKUP 从 MAIN sheet 查询：
        =VLOOKUP(trade_time&instrument_id, MAIN!col_tt:col_add, col_offset, FALSE)
    adj_price 用公式：
        =price_cell * adjust_mul_cell + adjust_add_cell

    约定：VLOOKUP 的查找范围是 MAIN sheet 的 trade_time 列到 adjustment_add 列。
    """
    main_nrows = 0
    for sheet_name in wb.sheetnames:
        if sheet_name == main_ws_name:
            main_nrows = wb[sheet_name].max_row
            break

    # 确定 MAIN sheet 中各列的字母
    main_ws = wb[main_ws_name]
    main_headers = [main_ws.cell(2, c).value for c in range(1, main_ws.max_column + 1)]
    main_tt_col = _find_col_idx(main_headers, CS_COL_TRADE_TIME)
    main_mul_col = _find_col_idx(main_headers, 'adjustment_mul')
    main_add_col = _find_col_idx(main_headers, 'adjustment_add')
    main_inst_col = _find_col_idx(main_headers, CS_COL_INSTRUMENT_ID)

    # VLOOKUP 查找范围（从 trade_time 到 adjustment_add）
    vlookup_range = f"'{main_ws_name}'!${_col_letter(main_tt_col)}${main_data_start_row}:${_col_letter(main_add_col)}${main_nrows}"

    for sheet_name in wb.sheetnames:
        if sheet_name == main_ws_name or sheet_name == '_SWITCHES':
            continue

        ws = wb[sheet_name]
        # Header 在 row 2（row 1 是注释行）
        headers = [ws.cell(2, c).value for c in range(1, ws.max_column + 1)]

        # 找关键列索引（1-based）
        tt_col = _find_col_idx(headers, CS_COL_TRADE_TIME)
        inst_col = _find_col_idx(headers, CS_COL_INSTRUMENT_ID)
        close_col = _find_col_idx(headers, CS_COL_CLOSE)

        if tt_col is None or close_col is None:
            print(f"  ⚠️ Sheet '{sheet_name}' 缺少关键列，跳过")
            continue

        # 在最后一列之后添加新列
        adj_start_col = len(headers) + 1

        # 添加 header（写入 row 2，与现有 header 同行）
        ws.cell(2, adj_start_col, 'adjustment_mul').fill = HEADER_FILL
        ws.cell(2, adj_start_col + 1, 'adjustment_add').fill = HEADER_FILL

        # adj_price 列（对每个 PRICE_COLS 创建）
        adj_price_cols = {}  # price_col_name -> formula_col_index
        formula_col = adj_start_col + 2
        for pc in PRICE_COLS:
            pc_idx = _find_col_idx(headers, pc)
            if pc_idx is None:
                continue
            adj_name = pc + '_adj'
            ws.cell(2, formula_col, adj_name).fill = HEADER_FILL
            adj_price_cols[pc] = (pc_idx, formula_col)
            formula_col += 1

        # 为每一行写入 Excel 公式（数据从 row 3 开始）
        for row in range(3, ws.max_row + 1):
            # ---- adjust_mul: VLOOKUP(trade_time & instrument_id, MAIN, col_mul, FALSE) ----
            tt_cell = ws.cell(row, tt_col)
            inst_cell = ws.cell(row, inst_col) if inst_col else None

            # 构造查找键：trade_time & instrument_id
            if inst_cell is not None:
                lookup_key = f'{tt_cell.coordinate}&{inst_cell.coordinate}'
            else:
                lookup_key = f'{tt_cell.coordinate}'

            # VLOOKUP: 需要把 trade_time&instrument_id 作为查找键。
            # 用 INDEX+MATCH 更可靠（因为 VLOOKUP 需要查找列在第一列）：
            # =INDEX(MAIN!adjust_mul列, MATCH(trade_time&instrument_id, MAIN!trade_time_col&MAIN!inst_col, 0))
            # 数组公式用 Ctrl+Shift+Enter，但这里只能写普通公式。
            #
            # 替代方案：直接在 MAIN sheet 中准备一个 helper 列 = trade_time&instrument_id
            # 这样合约 sheet 用 VLOOKUP 即可。
            #
            # 由于 MAIN sheet 中我们也会加 helper 列，这里用 VLOOKUP：
            # =VLOOKUP(trade_time_cell & instrument_id_cell, MAIN!helper_col:adjust_add_col, mul_offset, FALSE)
            #
            # helper 列在 MAIN 的 trade_time 之前。设 main_tt_col 是 trade_time
            # helper 列在 trade_time 左边一列，VLOOKUP 从 helper 开始。
            vlookup_col_start = _col_letter(main_tt_col - 1)  # helper 列
            vlookup_range_adj = (
                f"'{main_ws_name}'!${vlookup_col_start}${main_data_start_row}"
                f":${_col_letter(main_add_col)}${main_nrows}"
            )
            mul_col_offset = main_mul_col - (main_tt_col - 1)  # helper 是第 1 列

            mul_formula = (
                f'=VLOOKUP({lookup_key},'
                f'{vlookup_range_adj},'
                f'{mul_col_offset},FALSE)'
            )
            ws.cell(row, adj_start_col, mul_formula).fill = FORMULA_FILL

            mul_cell_ref = _col_letter(adj_start_col) + str(row)

            # ---- adjustment_add: 同样 VLOOKUP 或直接写 0 ----
            # 因为 add 总是 0，可以直接写 0
            ws.cell(row, adj_start_col + 1, 0).fill = FORMULA_FILL
            add_cell_ref = _col_letter(adj_start_col + 1) + str(row)

            # ---- adj_price = price * mul + add ----
            for pc, (pc_idx, f_col) in adj_price_cols.items():
                price_cell_ref = ws.cell(row, pc_idx).coordinate
                formula = f'={price_cell_ref}*{mul_cell_ref}+{add_cell_ref}'
                ws.cell(row, f_col, formula).fill = FORMULA_FILL

        print(f"  Sheet '{sheet_name}': added adjust_mul/add + {len(adj_price_cols)} adj_price cols")


# ------------------------------------------------------------
# 4. 插入 MAIN sheet (index=0) — 主力连续序列
# ------------------------------------------------------------

def _build_main_sheet(wb) -> str:
    """
    在 index=0 插入 MAIN sheet。
    从 _SWITCHES 和所有合约 sheet 拼接主力连续分钟序列。

    MAIN sheet 结构（Excel 公式）：
    - helper 列 (A): =trade_time&instrument_id（方便 VLOOKUP）
    - trade_time, trading_day, instrument_id, open_price, ..., adjustment_mul, adjustment_add

    adjustment_mul 公式：
      第 2 行（基准）: =1
      第 3 行起: =IF(instrument_id=上一行instrument_id, 上一行adjust_mul,
                     (上一行close_price/当前行close_price)*上一行adjust_mul)
    adjustment_add 公式：
      =0

    返回 MAIN sheet 的名称。
    """
    main_ws = wb.create_sheet('MAIN', 0)  # index=0

    # --- 收集所有合约的数据 ---
    # 从 _SWITCHES 获取切换顺序
    sw_ws = wb['_SWITCHES']
    # _SWITCHES header 在 row 2（row 1 是注释行）
    sw_headers = [sw_ws.cell(2, c).value for c in range(1, sw_ws.max_column + 1)]
    td_col_sw = _find_col_idx(sw_headers, SW_COL_TRADING_DAY)
    inst_col_sw = _find_col_idx(sw_headers, SW_COL_INSTRUMENT_ID)

    # 从各合约 sheet 收集所有数据行
    all_rows = []

    for sheet_name in wb.sheetnames:
        if sheet_name in ('_SWITCHES', 'MAIN'):
            continue
        ws = wb[sheet_name]
        headers = [ws.cell(2, c).value for c in range(1, ws.max_column + 1)]
        tt_col = _find_col_idx(headers, CS_COL_TRADE_TIME)
        td_col = _find_col_idx(headers, 'trading_day')
        inst_col = _find_col_idx(headers, CS_COL_INSTRUMENT_ID)
        close_col = _find_col_idx(headers, CS_COL_CLOSE)
        open_col = _find_col_idx(headers, CS_COL_OPEN)
        high_col = _find_col_idx(headers, CS_COL_HIGH)
        low_col = _find_col_idx(headers, CS_COL_LOW)
        settle_col = _find_col_idx(headers, 'settlement_price')
        vol_col = _find_col_idx(headers, 'volume')
        oi_col = _find_col_idx(headers, 'open_interest')
        turnover_col = _find_col_idx(headers, 'turnover')

        if tt_col is None or close_col is None:
            continue

        for row in range(3, ws.max_row + 1):
            tt = ws.cell(row, tt_col).value
            if tt is None:
                continue
            all_rows.append({
                'trade_time': tt,
                'trading_day': ws.cell(row, td_col).value if td_col else None,
                'instrument_id': ws.cell(row, inst_col).value if inst_col else sheet_name,
                'open_price': ws.cell(row, open_col).value if open_col else None,
                'highest_price': ws.cell(row, high_col).value if high_col else None,
                'lowest_price': ws.cell(row, low_col).value if low_col else None,
                'close_price': ws.cell(row, close_col).value,
                'settlement_price': ws.cell(row, settle_col).value if settle_col else None,
                'volume': ws.cell(row, vol_col).value if vol_col else None,
                'turnover': ws.cell(row, turnover_col).value if turnover_col else None,
                'open_interest': ws.cell(row, oi_col).value if oi_col else None,
            })

    # 按时间排序
    all_rows.sort(key=lambda r: r['trade_time'])

    # --- 写入 MAIN sheet ---
    # Row 1: Header
    # Col A: helper (=trade_time&instrument_id)
    # Col B onwards: 数据列

    helper_col = 1
    data_start_col = 2

    # Row 1: remark, Row 2: header (与 test_1 格式对齐)
    # 合并所有列写入 remark
    main_ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(MAIN_COLS) + 1)
    main_ws.cell(1, 1, '主力连续合约序列 — 由 test_2a 自动生成\nadjustment_mul=IF(instrument_id变化, 上一行close/当前行close*上一行mul, 上一行mul) | adjustment_add=0')

    headers_main = ['_VLOOKUP_KEY'] + MAIN_COLS  # helper + 数据列

    for c, h in enumerate(headers_main, 1):
        main_ws.cell(2, c, h).fill = HEADER_FILL

    # 写入数据（从 row=3 开始，row 1=remark, row 2=header）
    for i, r in enumerate(all_rows):
        row = i + 3  # Excel row (1-based)

        # 数据列
        main_ws.cell(row, 2, r['trade_time'])          # trade_time
        main_ws.cell(row, 3, r['trading_day'])         # trading_day
        main_ws.cell(row, 4, r['instrument_id'])       # instrument_id

        for ci, col_name in enumerate(MAIN_COLS[3:], 5):  # 从第 5 列开始（open_price 等）
            main_ws.cell(row, ci, r.get(col_name))

        # --- 写入 Excel 公式 ---
        # helper 列 (A): =trade_time & instrument_id
        tt_ref = _col_letter(2) + str(row)
        inst_ref = _col_letter(4) + str(row)
        main_ws.cell(row, helper_col, f'={tt_ref}&{inst_ref}').fill = FORMULA_FILL

        # adjustment_mul 列
        mul_col = 2 + len(MAIN_COLS) - 2  # helper(col1) + 数据列... adj_mul在倒数第2列
        # 实际上：A=_VLOOKUP_KEY(1), B=trade_time(2), C=trading_day(3), D=inst(4),
        # E=open(5), F=highest(6), G=lowest(7), H=close(8), I=settle(9),
        # J=vol(10), K=turnover(11), L=oi(12), M=adj_mul(13), N=adj_add(14)

        if row == 3:
            # 第一行数据：adjustment_mul = 1（基准值）
            main_ws.cell(row, mul_col, 1).fill = FORMULA_FILL
        else:
            # =IF(D{row}=D{row-1}, L{row-1}, H{row-1}/H{row}*L{row-1})
            prev_row = row - 1
            inst_cur = _col_letter(4) + str(row)
            inst_prev = _col_letter(4) + str(prev_row)
            mul_prev = _col_letter(mul_col) + str(prev_row)
            close_prev = _col_letter(8) + str(prev_row)    # H = close_price
            close_cur = _col_letter(8) + str(row)

            formula_mul = (
                f'=IF({inst_cur}={inst_prev},'
                f'{mul_prev},'
                f'{close_prev}/{close_cur}*{mul_prev})'
            )
            main_ws.cell(row, mul_col, formula_mul).fill = FORMULA_FILL

        # adjustment_add 列 (col 13)
        add_col = mul_col + 1
        main_ws.cell(row, add_col, 0).fill = FORMULA_FILL

    print(f"  MAIN sheet: {len(all_rows)} rows, {len(headers_main)} columns")
    print(f"  Excel formula: IF(inst_changed, prev_close/cur_close*prev_mul, prev_mul)")

    return 'MAIN'


# ------------------------------------------------------------
# 主流程
# ------------------------------------------------------------

def process_product(src_path: Path, dst_path: Path) -> None:
    """处理一个品种的 test_1 Excel。"""
    print(f"\n{'='*60}")
    print(f"Processing: {src_path.name}")

    wb = load_workbook(src_path)

    # Step 1: 插入 MAIN sheet (index=0)
    main_name = _build_main_sheet(wb)

    # Step 2: 为合约 sheet 添加 Excel 公式
    _add_formulas_to_contract_sheets(wb, main_name, main_data_start_row=3)

    # 保存
    print(f"  Saving to {dst_path.name}...")
    wb.save(dst_path)
    print(f"  ✅ Saved: {dst_path.name}")


def main():
    print("test_2a: Excel-formula adjustment verification")
    print("=" * 60)
    print("\n⛔ Note: test_1 data is pre-computed, NOT re-run here.")
    print(f"   Source: {TEST_1_DIR}")
    print(f"   Output: {TEST_2A_DIR}")

    # Step 0: 清空 + 复制
    print("\n📋 Step 0: Clear & copy from test_1...")
    _clear_and_copy()

    # Step 1-2: 处理每个 xlsx
    print("\n📋 Processing each product...")
    for xlsx_path in sorted(TEST_2A_DIR.glob('*.xlsx')):
        try:
            process_product(xlsx_path, xlsx_path)
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"Done! Output: {TEST_2A_DIR}")


if __name__ == '__main__':
    main()
