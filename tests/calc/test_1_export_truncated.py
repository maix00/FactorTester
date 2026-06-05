"""
test_1_export_truncated.py
--------------------------
从 test_0/_products.xlsx 的 _SWITCH_COUNTS sheet 读取品种列表，
从 wind_mapping.parquet 获取主力切换记录，从 data_mink_product/ 截取分钟数据。

每个品种 → 一个 Excel 文件：data/test/test_1/{prod}/{prod}.xlsx
  Sheet _SWITCHES: 从 wind_mapping 直接复制该品种在时间段内的主力切换记录
    含注释行说明数据来源
  Sheet {instrument_id}: 每个涉及的合约，在其主力区间前后各保留 WINDOW_ROWS 行分钟数据
    按最近切换日期降序排列

数据源：
  - test_0/_products.xlsx (_SWITCH_COUNTS sheet): 品种列表 + wind_exch/min_exch
  - wind_mapping.parquet: 主力切换记录 (_SWITCHES sheet 来源)
  - data_mink_product/: 分钟行情数据 (合约 sheet 来源)

Output: data/test/test_1/{prod}/{prod}.xlsx
"""

import json
import shutil
from datetime import date
from pathlib import Path

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter

from tests.calc import (
    WIND_MAPPING_PATH, MIN_DATA_DIR, TEST_0_PRODUCTS_XLSX, TEST_1_DIR,
    WINDOW_ROWS, WIND_EXCH_TO_MIN_EXCH,
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


def validate_test_1_complete() -> tuple[bool, list[str]]:
    """Check that test_1 has exported every product listed by test_0."""
    problems: list[str] = []

    products = _load_products_from_test0()
    expected = {str(p['prod']): p for p in products}
    if not expected:
        problems.append('test_0/_SWITCH_COUNTS has no products')
        return False, problems

    manifest_path = TEST_1_DIR / '_manifest.json'
    if not manifest_path.exists():
        problems.append(f'test_1 manifest not found: {manifest_path}')
        return False, problems

    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as exc:
        problems.append(f'test_1 manifest is invalid JSON: {exc}')
        return False, problems

    missing_manifest = sorted(set(expected) - set(manifest))
    if missing_manifest:
        problems.append(f'missing manifest entries: {", ".join(missing_manifest)}')

    for prod, pinfo in expected.items():
        entry = manifest.get(prod)
        if not isinstance(entry, dict):
            continue
        if 'error' in entry:
            problems.append(f'{prod}: manifest has error: {entry["error"]}')
            continue
        file_name = entry.get('file') or f'{prod}.xlsx'
        xlsx_path = TEST_1_DIR / file_name
        if not xlsx_path.exists():
            problems.append(f'{prod}: xlsx not found: {xlsx_path}')
            continue

        try:
            wb = load_workbook(xlsx_path, read_only=True, data_only=True)
            if '_SWITCHES' not in wb.sheetnames:
                problems.append(f'{prod}: missing _SWITCHES sheet')
                wb.close()
                continue

            ws = wb['_SWITCHES']
            switch_rows = max(ws.max_row - 2, 0)
            expected_switches = int(pinfo['switch_count'])
            if switch_rows != expected_switches:
                problems.append(
                    f'{prod}: _SWITCHES rows {switch_rows}, expected {expected_switches}'
                )

            contract_sheets = {sn for sn in wb.sheetnames if sn != '_SWITCHES'}
            listed_sheets = {
                str(s.get('instrument'))
                for s in entry.get('sheets', [])
                if isinstance(s, dict) and s.get('instrument')
            }
            if listed_sheets and contract_sheets != listed_sheets:
                missing = sorted(listed_sheets - contract_sheets)
                extra = sorted(contract_sheets - listed_sheets)
                if missing:
                    problems.append(f'{prod}: missing contract sheets: {", ".join(missing)}')
                if extra:
                    problems.append(f'{prod}: unexpected contract sheets: {", ".join(extra)}')
            if not contract_sheets:
                problems.append(f'{prod}: no contract sheets exported')
            wb.close()
        except Exception as exc:
            problems.append(f'{prod}: cannot inspect workbook: {exc}')

    return not problems, problems


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
# 分钟数据截取 helpers
# ================================================

def _normalize_trading_day(values: pd.Series) -> pd.Series:
    """Normalize trading_day to midnight timestamps without using trade_time."""
    if pd.api.types.is_numeric_dtype(values):
        parsed = pd.to_datetime(values.astype('Int64').astype(str), format='%Y%m%d', errors='coerce')
    else:
        parsed = pd.to_datetime(values, errors='coerce')
    return parsed.dt.normalize()


def _read_min_index(parquet_path: Path) -> pd.DataFrame:
    """Read only the columns needed to locate row windows."""
    df_idx = pd.read_parquet(parquet_path, columns=['trading_day', 'trade_time'])
    df_idx['trade_time'] = pd.to_datetime(df_idx['trade_time'])
    return df_idx.sort_values('trade_time').reset_index(drop=True)


def _select_window_rows(
    df_idx: pd.DataFrame,
    intervals: list[tuple[pd.Timestamp, pd.Timestamp]],
) -> tuple[pd.Series, list[tuple[int, int]]]:
    """Return a boolean mask over df_idx for主力区间前后 WINDOW_ROWS 行."""
    day_series = _normalize_trading_day(df_idx['trading_day'])
    mask = pd.Series(False, index=df_idx.index)
    selected_ranges: list[tuple[int, int]] = []

    for start_dt, end_dt in intervals:
        start_day = pd.Timestamp(start_dt).normalize()
        end_day = pd.Timestamp(end_dt).normalize()
        interval_pos = day_series[(day_series >= start_day) & (day_series <= end_day)].index
        if len(interval_pos) == 0:
            print(f"  [WARN] no rows for {start_day.date()} ~ {end_day.date()}")
            continue
        start_idx = max(int(interval_pos[0]) - WINDOW_ROWS, 0)
        end_idx = min(int(interval_pos[-1]) + WINDOW_ROWS, len(df_idx) - 1)
        mask.iloc[start_idx:end_idx + 1] = True
        selected_ranges.append((start_idx, end_idx))

    return mask, selected_ranges


def _read_selected_min_rows(parquet_path: Path, df_idx: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    """Read only selected trading days when possible, then keep exact selected rows."""
    selected_idx = df_idx.loc[mask, ['trading_day', 'trade_time']]
    if selected_idx.empty:
        return pd.DataFrame()

    selected_days = selected_idx['trading_day'].dropna().drop_duplicates().tolist()
    selected_times = pd.to_datetime(selected_idx['trade_time'])

    try:
        dfm = pd.read_parquet(parquet_path, filters=[('trading_day', 'in', selected_days)])
    except Exception:
        # Some parquet engines/files cannot apply filters for this dtype; keep correctness.
        dfm = pd.read_parquet(parquet_path)

    dfm['trade_time'] = pd.to_datetime(dfm['trade_time'])
    dfm = dfm[dfm['trade_time'].isin(selected_times)].copy()
    return dfm.sort_values('trade_time').reset_index(drop=True)


def _append_dataframe_rows(ws, df: pd.DataFrame) -> None:
    """Append DataFrame rows to an openpyxl sheet with minimal per-cell work."""
    df_out = df.copy()
    if 'trading_day' in df_out.columns:
        trading_day = df_out['trading_day']
        if pd.api.types.is_datetime64_any_dtype(trading_day):
            df_out['trading_day'] = trading_day.dt.date
    for row in dataframe_to_rows(df_out, index=False, header=False):
        ws.append(row)


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
    Sheet {inst}: 每个合约主力区间前后各保留 WINDOW_ROWS 行分钟数据
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
    # 合约 sheets: 主力区间 ±WINDOW_ROWS 行分钟数据
    # ================================================
    inst_intervals: dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]] = {}
    for _, sw_row in switches.iterrows():
        inst = sw_row['instrument_id']
        inst_intervals.setdefault(inst, []).append((sw_row['STARTDATE'], sw_row['ENDDATE']))

    # 找每个合约最近一次切换日用于排序
    inst_last_switch: dict[str, date] = {}
    for _, sw_row in switches.iterrows():
        inst = sw_row['instrument_id']
        sd = sw_row['STARTDATE'].date()
        if inst not in inst_last_switch or sd > inst_last_switch[inst]:
            inst_last_switch[inst] = sd

    # 按最近切换日期降序，导出全部合约
    sorted_insts = sorted(inst_intervals.keys(), key=lambda x: inst_last_switch[x], reverse=True)
    exported_count = 0

    for inst in sorted_insts:
        fn = inst_to_fname.get(inst)
        if fn is None:
            print(f"  [WARN] Missing min file for {inst}, skipping")
            continue

        parquet_path = MIN_DATA_DIR / fn
        try:
            df_idx = _read_min_index(parquet_path)
        except Exception as exc:
            print(f"  [WARN] Cannot read index columns for {inst}: {exc}")
            continue
        if 'trading_day' not in df_idx.columns:
            print(f"  [WARN] {inst} has no trading_day column, skipping")
            continue

        mask, selected_ranges = _select_window_rows(df_idx, inst_intervals[inst])
        df_win = _read_selected_min_rows(parquet_path, df_idx, mask)

        if len(df_win) == 0:
            print(f"  [SKIP] {inst} has 0 rows in selected row windows")
            continue

        # 全量导出 data_mink_product 的所有列
        cols = list(df_win.columns)


        sheet_name = str(inst)
        ws = wb.create_sheet(sheet_name)

        # 注释行
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(cols))
        inst_comment = (f"数据来源: {parquet_path}\n"
                        f"合约: {inst} (品种: {prod})\n"
                        f"截取口径: 每个主力区间前后各保留 {WINDOW_ROWS} 行分钟数据\n"
                        f"主力区间数: {len(inst_intervals[inst])}；选中原始行区间: {selected_ranges}")
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
        _append_dataframe_rows(ws, df_win)

        exported_count += 1
        first_ts = df_win['trade_time'].min().strftime('%Y-%m-%d %H:%M:%S')
        last_ts = df_win['trade_time'].max().strftime('%Y-%m-%d %H:%M:%S')
        print(f"  [{exported_count}] {inst}: {len(df_win)} rows ({first_ts} ~ {last_ts})")

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
