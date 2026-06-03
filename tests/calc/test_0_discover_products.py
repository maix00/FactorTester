"""
test_0_discover_products.py
----------------------------
统计分析：基于 wind_mapping.parquet 和 data_mink_product 分钟数据范围，
输出 data/test/test_0/_products.xlsx

数据源：
  - wind_mapping.parquet: Wind 主力合约映射表 (S_INFO_WINDCODE, FS_MAPPING_WINDCODE, STARTDATE, ENDDATE)
  - data_mink_product/: 分钟数据目录，每个合约一个 parquet，用于确定各品种的数据覆盖时间范围

Output Excel (openpyxl 直接写，含注释):
  Sheet _SUMMARY:
    每个品种在分钟数据覆盖范围内的连续主力日期范围
    Row 1: 注释（数据来源、计算说明）
    Row 2: headers
    Row 3+: 数据

  Sheet _SWITCH_COUNTS:
    每个品种在 _SUMMARY 的时间范围内，根据 wind_mapping 统计的合约切换次数
    Row 1: 注释（统计口径说明）
    Row 2: headers
    Row 3+: 数据

test_1 从 _SWITCH_COUNTS sheet 读取品种列表及参数。
"""

import pandas as pd
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from scripts.data_dir import DATA_DIR as _ROOT_DATA_DIR

DATA_DIR = Path(_ROOT_DATA_DIR)
WIND_MAPPING_PATH = DATA_DIR / 'wind_mapping.parquet'
MIN_DIR = DATA_DIR / 'data_mink_product'
OUTPUT_DIR = DATA_DIR / 'test' / 'test_0'

TOP_N = 8

# wind_mapping 交易所 → 分钟文件 交易所（SHF在分钟文件中可能写成SHFE）
WIND_EXCH_TO_MIN_EXCH: dict[str, str] = {
    'SHF': 'SHFE', 'DCE': 'DCE', 'CZC': 'CZC',
    'INE': 'INE', 'CFE': 'CFE', 'GFE': 'GFE',
}

# 样式
COMMENT_FILL = PatternFill(start_color='FFFCE4D6', end_color='FFFCE4D6', fill_type='solid')  # 浅橙注释色
HEADER_FILL = PatternFill(start_color='FFD9E1F2', end_color='FFD9E1F2', fill_type='solid')   # 浅蓝表头色
HEADER_FONT = Font(bold=True)
COMMENT_FONT = Font(italic=True, size=10)


def _find_min_exch(prod: str, wind_exch: str) -> str | None:
    """查找该品种分钟数据使用的交易所代码"""
    for exch in (WIND_EXCH_TO_MIN_EXCH.get(wind_exch, wind_exch), wind_exch):
        prefix = f'{exch}|F|{prod}|'
        if list(MIN_DIR.glob(f'{prefix}*.parquet')):
            return exch
    return None


def _get_min_data_range(prod: str, min_exch: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """获取某品种所有分钟文件的 trade_time 最小/最大值"""
    prefix = f'{min_exch}|F|{prod}|'
    files = list(MIN_DIR.glob(f'{prefix}*.parquet'))
    if not files:
        return None
    t_min, t_max = None, None
    for fp in files:
        df = pd.read_parquet(fp)
        tt = pd.to_datetime(df['trade_time'])
        if t_min is None:
            t_min, t_max = tt.min(), tt.max()
        else:
            t_min = min(t_min, tt.min())
            t_max = max(t_max, tt.max())
    return pd.Timestamp(t_min), pd.Timestamp(t_max)


def _style_header(ws, num_cols: int):
    """给第2行（表头）加样式"""
    for col in range(1, num_cols + 1):
        cell = ws.cell(row=2, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT


def _write_comment_row(ws, comment_text: str, num_cols: int):
    """在第1行写注释，合并单元格并加样式"""
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=num_cols)
    cell = ws.cell(row=1, column=1, value=comment_text)
    cell.fill = COMMENT_FILL
    cell.font = COMMENT_FONT
    cell.alignment = Alignment(wrap_text=True)
    ws.row_dimensions[1].height = 40


def main():
    start_time = pd.Timestamp.now()

    if not WIND_MAPPING_PATH.exists():
        raise FileNotFoundError(f"wind_mapping not found: {WIND_MAPPING_PATH}")

    wm = pd.read_parquet(WIND_MAPPING_PATH)

    # 排除 _S 后缀的跨品种套利（如 CU_S.SHF）
    wm = wm[~wm['S_INFO_WINDCODE'].str.contains(r'_S\.')].copy()
    wm = wm.dropna(subset=['STARTDATE', 'ENDDATE', 'FS_MAPPING_WINDCODE'])
    wm['STARTDATE'] = pd.to_datetime(wm['STARTDATE'])
    wm['ENDDATE'] = pd.to_datetime(wm['ENDDATE'])

    # ================================================
    # Sheet _SUMMARY: 每个品种的分钟数据覆盖范围
    # ================================================
    summary_rows = []
    for windcode, grp in wm.groupby('S_INFO_WINDCODE'):
        parts = windcode.split('.')
        prod, wind_exch = parts[0], parts[1]
        min_exch = _find_min_exch(prod, wind_exch)
        if min_exch is None:
            continue
        dr = _get_min_data_range(prod, min_exch)
        if dr is None:
            continue
        data_start, data_end = dr
        summary_rows.append({
            'prod': prod,
            'wind_exch': wind_exch,
            'min_exch': min_exch,
            'data_start': data_start.date(),
            'data_end': data_end.date(),
        })

    summary_df = pd.DataFrame(summary_rows).sort_values('prod')
    summary_cols = ['prod', 'wind_exch', 'min_exch', 'data_start', 'data_end']

    # ================================================
    # Sheet _SWITCH_COUNTS: 在分钟数据范围内统计 wind_mapping 切换次数
    # ================================================
    switch_rows = []
    for _, row in summary_df.iterrows():
        prod = row['prod']
        wind_exch = row['wind_exch']
        min_exch = row['min_exch']
        data_start = pd.Timestamp(row['data_start'])
        data_end = pd.Timestamp(row['data_end'])

        wc = f'{prod}.{wind_exch}'
        prod_wm = wm[wm['S_INFO_WINDCODE'] == wc].copy()

        # 只统计 STARTDATE 落在分钟数据范围内的切换
        prod_wm = prod_wm[
            (prod_wm['STARTDATE'] >= data_start) &
            (prod_wm['STARTDATE'] <= data_end)
        ]
        switch_count = len(prod_wm)
        if switch_count == 0:
            continue

        switch_rows.append({
            'prod': prod,
            'wind_exch': wind_exch,
            'min_exch': min_exch,
            'switch_count': switch_count,
            'data_start': data_start.date(),
            'data_end': data_end.date(),
        })

    switch_df = pd.DataFrame(switch_rows).sort_values('switch_count', ascending=False)
    switch_cols = ['prod', 'wind_exch', 'min_exch', 'switch_count', 'data_start', 'data_end']

    # ================================================
    # 写 Excel (openpyxl 直接写，加注释行)
    # ================================================
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / '_products.xlsx'

    wb = Workbook()
    wb.remove(wb.active)

    # --- _SUMMARY sheet ---
    ws_sum = wb.create_sheet('_SUMMARY')
    _write_comment_row(ws_sum,
        f"数据来源: wind_mapping.parquet + data_mink_product/\n"
        f"计算逻辑: 遍历每个品种(S_INFO_WINDCODE)，通过 data_mink_product 目录下的分钟 parquet 文件，"
        f"取该品种所有合约 trade_time 的最小/最大值，得到该品种的数据覆盖范围 [data_start, data_end]。\n"
        f"wind_exch=wind_mapping中的交易所代码，min_exch=data_mink_product 目录中使用的交易所代码。\n"
        f"排除 _S 后缀的跨品种套利。\n"
        f"生成时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}",
        len(summary_cols))

    for ci, col_name in enumerate(summary_cols, 1):
        ws_sum.cell(row=2, column=ci, value=col_name)
    _style_header(ws_sum, len(summary_cols))

    for ri, (_, row) in enumerate(summary_df.iterrows(), 3):
        for ci, col_name in enumerate(summary_cols, 1):
            ws_sum.cell(row=ri, column=ci, value=row[col_name])

    # 自动列宽
    for ci in range(1, len(summary_cols) + 1):
        ws_sum.column_dimensions[get_column_letter(ci)].width = 16

    # --- _SWITCH_COUNTS sheet ---
    ws_sw = wb.create_sheet('_SWITCH_COUNTS')
    _write_comment_row(ws_sw,
        f"数据来源: wind_mapping.parquet (限定在 _SUMMARY 中的 data_start ~ data_end 范围内)\n"
        f"统计口径: 对每个品种，筛选 wind_mapping 中 STARTDATE 落在 [data_start, data_end] 区间的记录，"
        f"COUNT 即 switch_count。切换次数越多 → 该品种主力合约更替越频繁 → 更适合做复权验证。\n"
        f"test_1 将从此 sheet 取 switch_count 最高的几个品种做导出。\n"
        f"生成时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}",
        len(switch_cols))

    for ci, col_name in enumerate(switch_cols, 1):
        ws_sw.cell(row=2, column=ci, value=col_name)
    _style_header(ws_sw, len(switch_cols))

    for ri, (_, row) in enumerate(switch_df.iterrows(), 3):
        for ci, col_name in enumerate(switch_cols, 1):
            ws_sw.cell(row=ri, column=ci, value=row[col_name])

    for ci in range(1, len(switch_cols) + 1):
        ws_sw.column_dimensions[get_column_letter(ci)].width = 16

    wb.save(output_path)

    # ================================================
    # 打印结果
    # ================================================
    print(f"[test_0] Total products with min data: {len(summary_df)}")
    print(f"\n[test_0] Top {TOP_N} by switch_count:")
    for i, (_, row) in enumerate(switch_df.head(TOP_N).iterrows()):
        print(f"  {i+1}. {row['prod']} ({row['wind_exch']}): {row['switch_count']} switches "
              f"in {row['data_start']} ~ {row['data_end']} (min={row['min_exch']})")

    print(f"\n[test_0] Output: {output_path}")
    print(f"  _SUMMARY: {len(summary_df)} rows")
    print(f"  _SWITCH_COUNTS: {len(switch_df)} rows")



if __name__ == '__main__':
    main()
