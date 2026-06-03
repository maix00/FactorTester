"""
test_2a_adjustment_verify.py
-----------------------------
从 test_1 的 Excel 复制一份，添加前复权因子及 Excel 公式计算的复权价格。

对每个品种的 test_1 Excel：
1. 在 _SWITCHES sheet 中补充主连数据的 adjustment_mul 和 adjustment_add
2. 在每个合约 sheet 中插入 adjustment_mul/adjustment_add 列（从主连数据查找）
3. 插入 Excel 公式：open_adj / high_adj / low_adj / close_adj = price * mul + add

Output: data/test/test_2a/{prod}.xlsx
"""

import re
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.styles import Font, PatternFill

from tests.calc import (
    WIND_MAPPING_PATH, MIN_DATA_DIR, TEST_1_DIR, TEST_2A_DIR,
    TOP_N,
)

# --- test_2a 专用数据源（不在 calc 白名单中，单独声明） ---
from scripts.data_dir import DATA_DIR as _ROOT_DATA_DIR
MAIN_MINK_DIR = Path(_ROOT_DATA_DIR) / 'main_mink'

# test_0 发现的品种 — 从 Excel 读取（与 test_1 相同方式）
# 注意：test_2a 尚未运行，这里先用占位，后续修复
TOP_PRODUCTS: dict[str, tuple[str, str]] = {}  # prod -> (day_exch, _)

# 复权公式的颜色标记（浅黄底色，方便识别）
FORMULA_FILL = PatternFill(start_color='FFFFF2CC', end_color='FFFFF2CC', fill_type='solid')
HEADER_FILL = PatternFill(start_color='FFD9E1F2', end_color='FFD9E1F2', fill_type='solid')

PRICE_COLS = ['open_price', 'high_price', 'low_price', 'close_price']
ADJ_SUFFIX = '_adj'


def _load_main_adjustments(prod: str, day_exch: str) -> pd.DataFrame:
    """加载主连分钟数据中的 adjustment 信息"""
    exch_normalized = {'SHF': 'SHFE'}.get(day_exch, day_exch)
    for exch in (exch_normalized, 'SHF' if exch_normalized == 'SHFE' else day_exch):
        f = MAIN_MINK_DIR / f'{prod}.{exch}.parquet'
        if f.exists():
            break
    else:
        # glob fallback
        for g in sorted(MAIN_MINK_DIR.glob(f'{prod}.*.parquet')):
            f = g
            break
        else:
            raise FileNotFoundError(f"Cannot find main_mink file for {prod}")

    df = pd.read_parquet(f)
    df['trade_time'] = pd.to_datetime(df['trade_time'])
    return df[['trade_time', 'instrument_id', 'adjustment_mul', 'adjustment_add']].copy()


def _get_adj_for_row(trade_time: pd.Timestamp, inst: str, main_df: pd.DataFrame) -> tuple[float, float]:
    """查找某时刻某合约的 adjustment_mul 和 adjustment_add"""
    mask = (main_df['trade_time'] == trade_time) & (main_df['instrument_id'] == inst)
    match = main_df.loc[mask]
    if len(match) == 1:
        return float(match.iloc[0]['adjustment_mul']), float(match.iloc[0]['adjustment_add'])
    # fallback: nearest time match
    inst_mask = main_df['instrument_id'] == inst
    inst_df = main_df[inst_mask]
    if len(inst_df) == 0:
        return 1.0, 0.0
    idx = (inst_df['trade_time'] - trade_time).abs().idxmin()
    return float(inst_df.loc[idx, 'adjustment_mul']), float(inst_df.loc[idx, 'adjustment_add'])


def _find_price_col_index(headers: list[str], col_name: str) -> int | None:
    """在 header 行中找到列索引（1-based）"""
    for i, h in enumerate(headers, 1):
        if h == col_name:
            return i
    return None


def process_product(prod: str, day_exch: str) -> Path:
    """处理一个品种：复制 test_1 Excel，添加复权公式"""
    input_path = TEST_1_DIR / prod / f'{prod}.xlsx'
    if not input_path.exists():
        raise FileNotFoundError(f"test_1 Excel not found: {input_path}")

    output_dir = TEST_2A_DIR / prod
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f'{prod}.xlsx'

    # 加载主连数据
    print(f"  Loading main_mink adjustments for {prod}...")
    main_df = _load_main_adjustments(prod, day_exch)

    # 用 openpyxl 打开（保留原格式）
    wb = load_workbook(input_path)

    # --- 增强 _SWITCHES sheet ---
    ws_sw = wb['_SWITCHES']
    # 找到 adjustment_mul 和 adjustment_add 列位置（如果已有）
    headers_sw = [ws_sw.cell(1, c).value for c in range(1, ws_sw.max_column + 1)]
    
    # _SWITCHES 可能已有 adjustment_mul/adjustment_add，找位置或用最后一列后的位置
    mul_col_sw = _find_price_col_index(headers_sw, 'main_adj_mul')
    add_col_sw = _find_price_col_index(headers_sw, 'main_adj_add')
    
    if mul_col_sw is None:
        mul_col_sw = len(headers_sw) + 1
    if add_col_sw is None:
        add_col_sw = mul_col_sw + 1

    ws_sw.cell(1, mul_col_sw, 'main_adj_mul').fill = HEADER_FILL
    ws_sw.cell(1, add_col_sw, 'main_adj_add').fill = HEADER_FILL

    # 从 _SWITCHES 读取切换日信息
    # 找 trading_day 和 instrument_id 列
    td_col_sw = _find_price_col_index(headers_sw, 'trading_day')
    inst_col_sw = _find_price_col_index(headers_sw, 'instrument_id')

    # 为 _SWITCHES 的每行填入主连 adjustment
    for row in range(2, ws_sw.max_row + 1):
        td_val = ws_sw.cell(row, td_col_sw).value
        inst_val = ws_sw.cell(row, inst_col_sw).value
        if td_val is None or inst_val is None:
            continue
        trade_time = pd.Timestamp(td_val)
        mul, add = _get_adj_for_row(trade_time, inst_val, main_df)
        ws_sw.cell(row, mul_col_sw, mul).fill = FORMULA_FILL
        ws_sw.cell(row, add_col_sw, add).fill = FORMULA_FILL

    # --- 为每个合约 sheet 添加复权列 ---
    for sheet_name in wb.sheetnames:
        if sheet_name == '_SWITCHES':
            continue

        ws = wb[sheet_name]
        headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]

        # 找 trade_time 和 instrument_id 列
        tt_col = _find_price_col_index(headers, 'trade_time')
        inst_col = _find_price_col_index(headers, 'instrument_id')

        # 找添加列的位置（在最后一列之后）
        adj_start_col = len(headers) + 1

        # 添加 adjustment_mul / adjustment_add 列
        ws.cell(1, adj_start_col, 'adjustment_mul').fill = HEADER_FILL
        ws.cell(1, adj_start_col + 1, 'adjustment_add').fill = HEADER_FILL

        # 为每个价格列添加 Excel 公式：price * mul + add
        adj_col_map = {}  # price_col_name -> formula_column_index
        formula_col = adj_start_col + 2
        for pc in PRICE_COLS:
            pc_idx = _find_price_col_index(headers, pc)
            if pc_idx is None:
                continue
            adj_name = pc + ADJ_SUFFIX
            ws.cell(1, formula_col, adj_name).fill = HEADER_FILL
            adj_col_map[pc] = (pc_idx, formula_col)
            formula_col += 1

        # 填数据
        for row in range(2, ws.max_row + 1):
            tt_val = ws.cell(row, tt_col).value
            inst_val = ws.cell(row, inst_col).value
            if tt_val is None:
                continue

            trade_time = pd.Timestamp(tt_val)
            mul, add = _get_adj_for_row(trade_time, inst_val, main_df)

            mul_cell = ws.cell(row, adj_start_col, mul)
            add_cell = ws.cell(row, adj_start_col + 1, add)
            mul_cell.fill = FORMULA_FILL
            add_cell.fill = FORMULA_FILL

            # Excel 公式：价格 * adjustment_mul + adjustment_add
            for pc, (price_col, f_col) in adj_col_map.items():
                # 使用 openpyxl 公式语法
                price_ref = ws.cell(row, price_col).coordinate
                mul_ref = mul_cell.coordinate
                add_ref = add_cell.coordinate
                formula = f'={price_ref}*{mul_ref}+{add_ref}'
                cell = ws.cell(row, f_col, formula)
                cell.fill = FORMULA_FILL

        print(f"  Sheet '{sheet_name}': added adj_mul/adj_add + {len(adj_col_map)} price formulas")

    wb.save(output_path)
    return output_path


def main():
    output_base = TEST_2A_DIR
    output_base.mkdir(parents=True, exist_ok=True)

    for prod, (day_exch, _) in TOP_PRODUCTS.items():
        print(f"\n{'='*60}")
        print(f"Processing {prod} ({day_exch})...")
        try:
            out_path = process_product(prod, day_exch)
            print(f"  -> {out_path.name}")
        except Exception as e:
            print(f"  ERROR: {e}")


if __name__ == '__main__':
    main()
