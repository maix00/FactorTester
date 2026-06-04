"""
test_1_export_truncated.py
--------------------------
从 test_0/_products.xlsx 的 _SWITCH_COUNTS sheet 读取品种列表，
从 wind_mapping.parquet 获取主力切换记录，从 data_mink_product/ 截取分钟数据。

每个品种 → 一个 Excel 文件：data/test/test_1/{prod}/{prod}.xlsx
  Sheet _SWITCHES: 从 wind_mapping 直接复制该品种在时间段内的主力切换记录
    含注释行说明数据来源
  Sheet {instrument_id}: 每个涉及的合约，在其涉及时间范围 ±2 天的分钟数据
    按最近切换日期降序排列

数据源：
  - test_0/_products.xlsx (_SWITCH_COUNTS sheet): 品种列表 + wind_exch/min_exch
  - wind_mapping.parquet: 主力切换记录 (_SWITCHES sheet 来源)
  - data_mink_product/: 分钟行情数据 (合约 sheet 来源)

Output: data/test/test_1/{prod}/{prod}.xlsx
"""

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter

from tests.calc import (
    WIND_MAPPING_PATH, MIN_DATA_DIR, TEST_0_PRODUCTS_XLSX, TEST_1_DIR,
    WINDOW_DAYS, WIND_EXCH_TO_MIN_EXCH,
    HEADER_FILL, REMARK_FILL, REMARK_FONT, COMMENT_FONT,
)


# ================================================
# 从 test_0/_products.xlsx 读取品种列表
# ================================================

def _load_products_from_test0() -> list[dict]:
    """从 test_0/_products.xlsx 的 _SWITCH_COUNTS sheet 读取全部品种"""
    if not TEST_0_PRODUCTS_XLSX.exists():
        raise FileNotFoundError(f"test_0 output not found: {TEST_0_PRODUCTS_XLSX}\n"
                                f"Please run test_0_discover_products.py first.")

    df = pd.read_excel(TEST_0_PRODUCTS_XLSX, sheet_name='_SWITCH_COUNTS', header=1)
    # 全部品种（不限 TOP_N）
    products = []
    for _, row in df.iterrows():
        products.append({
            'prod': row['prod'],
            'wind_exch': row['wind_exch'],
            'min_exch': row['min_exch'],
            'switch_count': int(row['switch_count']),
            'data_start': pd.Timestamp(row['data_start']),
            'data_end': pd.Timestamp(row['data_end']),
        })
    return products


# ================================================
# 从 wind_mapping.parquet 读取切换记录
# ================================================

def _load_wind_mapping(prod: str, wind_exch: str,
                       data_start: pd.Timestamp, data_end: pd.Timestamp) -> pd.DataFrame:
    """从 wind_mapping 读取某品种在时间段内的切换记录"""
    wm = pd.read_parquet(WIND_MAPPING_PATH)

    # 排除 _S 后缀
    wm = wm[~wm['S_INFO_WINDCODE'].str.contains(r'_S\.')].copy()
    wm = wm.dropna(subset=['STARTDATE', 'ENDDATE', 'FS_MAPPING_WINDCODE'])
    wm['STARTDATE'] = pd.to_datetime(wm['STARTDATE'])
    wm['ENDDATE'] = pd.to_datetime(wm['ENDDATE'])

    wc = f'{prod}.{wind_exch}'
    prod_wm = wm[wm['S_INFO_WINDCODE'] == wc].copy()

    # 限定在分钟数据范围内
    prod_wm = prod_wm[
        (prod_wm['STARTDATE'] >= data_start) &
        (prod_wm['STARTDATE'] <= data_end)
    ].copy()

    # 转换 instrument_id: CU2507.SHF → cu2507
    prod_wm['instrument_id'] = prod_wm['FS_MAPPING_WINDCODE'].str.split('.').str[0].str.lower()
    prod_wm['trading_day'] = prod_wm['STARTDATE'].dt.date

    return prod_wm.sort_values('trading_day').reset_index(drop=True)


# ================================================
# 查找分钟文件
# ================================================

def _find_min_files(prod: str, min_exch: str) -> dict[str, str]:
    """返回 {instrument_id: filename} 映射"""
    for exch in (min_exch, 'SHFE' if min_exch == 'SHF' else min_exch):
        prefix = f'{exch}|F|{prod}|'
        files = sorted(MIN_DATA_DIR.glob(f'{prefix}*.parquet'))
        if files:
            break
    else:
        raise FileNotFoundError(f"Cannot find min files for {min_exch}|F|{prod}|*")
    inst_to_fname = {}
    for fp in files:
        code = fp.name.replace('.parquet', '').split('|')[-1]
        inst = f'{prod.lower()}{code}'
        inst_to_fname[inst] = fp.name
    return inst_to_fname


# ================================================
# 导出单个品种
# ================================================

def _export_product(
    prod: str,
    wind_exch: str,
    min_exch: str,
    switches: pd.DataFrame,
    inst_to_fname: dict[str, str],
    output_dir: Path,
    data_start: pd.Timestamp,
    data_end: pd.Timestamp,
) -> Path:
    """为一个品种导出 Excel：
    Sheet _SWITCHES: wind_mapping 切换记录
    Sheet {inst}: 每个合约 ±WINDOW_DAYS 的分钟数据
    """
    output_path = output_dir / f'{prod}.xlsx'

    wb = Workbook()
    if wb.active is not None:
        wb.remove(wb.active)

    # ================================================
    # Sheet _SWITCHES: 从 wind_mapping 复制切换记录
    # ================================================
    sw_cols = ['trading_day', 'instrument_id', 'FS_MAPPING_WINDCODE', 'STARTDATE', 'ENDDATE']
    sw_labels = {
        'trading_day': 'trading_day',
        'instrument_id': 'instrument_id',
        'FS_MAPPING_WINDCODE': 'windcode',
        'STARTDATE': 'start_date',
        'ENDDATE': 'end_date',
    }

    ws_sw = wb.create_sheet('_SWITCHES')
    # 注释行
    ws_sw.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(sw_cols))
    comment = (f"数据来源: wind_mapping.parquet ({WIND_MAPPING_PATH})\n"
               f"品种: {prod}.{wind_exch}\n"
               f"时间范围: {data_start.date()} ~ {data_end.date()} (data_mink_product 覆盖范围)\n"
               f"columns: trading_day=切换生效日, instrument_id=主力合约代码, "
               f"windcode=Wind合约代码, start_date/end_date=主力区间")
    cell = ws_sw.cell(row=1, column=1, value=comment)
    cell.fill = REMARK_FILL
    cell.font = COMMENT_FONT
    cell.alignment = Alignment(wrap_text=True)
    ws_sw.row_dimensions[1].height = 60

    # 表头
    for ci, col in enumerate(sw_cols, 1):
        c = ws_sw.cell(row=2, column=ci, value=sw_labels.get(col, col))
        c.fill = HEADER_FILL
        c.font = REMARK_FONT

    # 数据
    for ri, (_, sw_row) in enumerate(switches.iterrows(), 3):
        for ci, col in enumerate(sw_cols, 1):
            val = sw_row[col]
            if hasattr(val, 'date'):
                val = val.date()
            ws_sw.cell(row=ri, column=ci, value=val)

    for ci in range(1, len(sw_cols) + 1):
        ws_sw.column_dimensions[get_column_letter(ci)].width = 18

    # ================================================
    # 合约 sheets: ±WINDOW_DAYS 的分钟数据
    # ================================================
    # 对每个 instrument_id 取最大时间跨度（±WINDOW_DAYS）
    inst_spans: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    for _, sw_row in switches.iterrows():
        inst = sw_row['instrument_id']
        start_dt = sw_row['STARTDATE']
        end_dt = sw_row['ENDDATE']
        start = start_dt - timedelta(days=WINDOW_DAYS)
        end = end_dt + timedelta(days=WINDOW_DAYS)
        if inst not in inst_spans:
            inst_spans[inst] = (start, end)
        else:
            prev_start, prev_end = inst_spans[inst]
            inst_spans[inst] = (min(prev_start, start), max(prev_end, end))

    # 找每个合约最近一次切换日用于排序
    inst_last_switch: dict[str, date] = {}
    for _, sw_row in switches.iterrows():
        inst = sw_row['instrument_id']
        sd = sw_row['STARTDATE'].date()
        if inst not in inst_last_switch or sd > inst_last_switch[inst]:
            inst_last_switch[inst] = sd

    # 按最近切换日期降序，导出全部合约
    sorted_insts = sorted(inst_spans.keys(), key=lambda x: inst_last_switch[x], reverse=True)
    exported_count = 0

    for inst in sorted_insts:
        fn = inst_to_fname.get(inst)
        if fn is None:
            print(f"  [WARN] Missing min file for {inst}, skipping")
            continue

        start_ts, end_ts = inst_spans[inst]
        # end 扩展到当天结束
        end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

        dfm = pd.read_parquet(MIN_DATA_DIR / fn)
        dfm['trade_time'] = pd.to_datetime(dfm['trade_time'])
        mask = (dfm['trade_time'] >= start_ts) & (dfm['trade_time'] <= end_ts)
        df_win = dfm.loc[mask].copy()
        df_win = df_win.sort_values('trade_time').reset_index(drop=True)

        if len(df_win) == 0:
            print(f"  [SKIP] {inst} has 0 rows in merged span")
            continue

        # 全量导出 data_mink_product 的所有列
        cols = list(df_win.columns)


        sheet_name = str(inst)
        ws = wb.create_sheet(sheet_name)

        # 注释行
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(cols))
        inst_comment = (f"数据来源: {MIN_DATA_DIR / fn}\n"
                        f"合约: {inst} (品种: {prod})\n"
                        f"时间范围: {start_ts.strftime('%Y-%m-%d')} ~ {end_ts.strftime('%Y-%m-%d')} "
                        f"(±{WINDOW_DAYS}天 于切换区间 {inst_spans[inst][0].strftime('%Y-%m-%d')} ~ "
                        f"{(inst_spans[inst][1]).strftime('%Y-%m-%d')})")
        c = ws.cell(row=1, column=1, value=inst_comment)
        c.fill = REMARK_FILL
        c.font = COMMENT_FONT
        c.alignment = Alignment(wrap_text=True)
        ws.row_dimensions[1].height = 45

        # 表头
        for ci, col_name in enumerate(cols, 1):
            c = ws.cell(row=2, column=ci, value=col_name)
            c.fill = HEADER_FILL
            c.font = REMARK_FONT

        # 数据
        for ri, (_, drow) in enumerate(df_win.iterrows(), 3):
            for ci, col_name in enumerate(cols, 1):
                val = drow[col_name]
                if col_name == 'trading_day' and hasattr(val, 'date'):
                    val = val.date()
                ws.cell(row=ri, column=ci, value=val)

        exported_count += 1
        span_start = start_ts.strftime('%Y-%m-%d')
        span_end = end_ts.strftime('%Y-%m-%d')
        print(f"  [{exported_count}] {inst}: {len(df_win)} rows ({span_start} ~ {span_end})")

    wb.save(output_path)
    return output_path


# ================================================
# 主流程
# ================================================

def main():
    products = _load_products_from_test0()
    print(f"[test_1] Loaded {len(products)} products from test_0/_products.xlsx")
    for p in products:
        print(f"  {p['prod']} ({p['wind_exch']}): {p['switch_count']} switches "
              f"in {p['data_start'].date()} ~ {p['data_end'].date()} (min={p['min_exch']})")

    # 清空 test_1 目录下所有旧文件（包括旧子目录）
    if TEST_1_DIR.exists():
        for item in TEST_1_DIR.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    TEST_1_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[test_1] Cleaned {TEST_1_DIR}")

    manifest = {}
    for pinfo in products:
        prod = pinfo['prod']
        wind_exch = pinfo['wind_exch']
        min_exch = pinfo['min_exch']
        data_start = pinfo['data_start']
        data_end = pinfo['data_end']

        print(f"\n{'='*60}")
        print(f"Processing {prod} ({wind_exch})...")

        # 从 wind_mapping 读取切换记录
        switches = _load_wind_mapping(prod, wind_exch, data_start, data_end)
        print(f"  Switches: {len(switches)}")

        # 查找分钟文件
        inst_to_fname = _find_min_files(prod, min_exch)
        print(f"  Min files: {len(inst_to_fname)}")

        output_dir = TEST_1_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            out_path = _export_product(
                prod, wind_exch, min_exch, switches, inst_to_fname,
                output_dir, data_start, data_end,
            )

            # 收集 sheet 信息
            inst_last = {}
            for _, sw_row in switches.iterrows():
                inst = sw_row['instrument_id']
                sd = sw_row['STARTDATE'].date()
                if inst not in inst_last or sd > inst_last[inst]:
                    inst_last[inst] = sd
            sorted_insts = sorted(inst_last.keys(), key=lambda x: inst_last[x], reverse=True)
            sheet_list = [{'instrument': inst, 'last_switch': inst_last[inst].isoformat()}
                          for inst in sorted_insts]

            manifest[prod] = {
                'wind_exch': wind_exch,
                'min_exch': min_exch,
                'switch_count': len(switches),
                'file': out_path.name,
                'sheets': sheet_list,
            }
            print(f"  -> {out_path.name}")
        except Exception as e:
            print(f"  ERROR: {e}")
            manifest[prod] = {
                'wind_exch': wind_exch,
                'min_exch': min_exch,
                'switch_count': len(switches) if isinstance(switches, pd.DataFrame) else 0,
                'error': str(e),
            }

    # 写 manifest
    manifest_path = TEST_1_DIR / '_manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str, ensure_ascii=False))
    print(f"\n{'='*60}")
    print(f"Manifest: {manifest_path}")
    total_files = sum(1 for m in manifest.values() if 'file' in m)
    print(f"Total files: {total_files}")


if __name__ == '__main__':
    main()
