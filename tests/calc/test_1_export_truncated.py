"""
test_1_export_truncated.py
--------------------------
从 test_0 自动获取 TOP N 品种，导出每个切换日的 ±30 天截断数据到 Excel。

每个切换日 → 一个 Excel 文件：{prod}_{switch_date}.xlsx
- Sheet _SWITCHES：该品种完整切换表
- Sheet {instrument_id}：该合约 ±30 天内的分钟数据

Output: data/test/truncated/{prod}/{prod}_{switch_date}.xlsx + _manifest.json
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows

from scripts.data_dir import DATA_DIR as _ROOT_DATA_DIR

# --- test_0 自动发现的品种 ---
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_0_discover_products import TOP_PRODUCTS

# --- 路径配置 ---
DATA_DIR = Path(_ROOT_DATA_DIR)
MIN_DIR = DATA_DIR / 'data_mink_product'
DAY_DIR = DATA_DIR / 'main_dayk'
OUTPUT_BASE = DATA_DIR / 'test' / 'truncated'
WINDOW_DAYS = 30
MIN_DATE = date(2024, 1, 1)

# 日线文件交易所名 → 分钟文件交易所名（少数品种可能不同）
EXCH_OVERRIDE: dict[str, str] = {}  # prod -> forced min_exch if auto-detect fails


def _find_day_file(prod: str, day_exch: str) -> Path:
    """查找日线 parquet 文件，处理 SHF vs SHFE 等命名差异"""
    # 标准化 SHF → SHFE
    day_exch_normalized = {'SHF': 'SHFE'}.get(day_exch, day_exch)

    f = DAY_DIR / f'{prod}.{day_exch_normalized}.parquet'
    if f.exists():
        return f
    # 尝试简写 SHF
    if day_exch_normalized == 'SHFE':
        f = DAY_DIR / f'{prod}.SHF.parquet'
        if f.exists():
            return f
    # fallback: glob
    for g in sorted(DAY_DIR.glob(f'{prod}.*.parquet')):
        if '_S' not in g.name and 'adjusted' not in g.name.lower():
            return g
    raise FileNotFoundError(f"Cannot find day file for {prod} ({day_exch})")


def _find_min_files(prod: str, min_exch: str) -> dict[str, str]:
    """返回 {instrument_id: filename} 映射"""
    # 标准化 SHF → SHFE（分钟文件也可能用简写）
    for exch in (min_exch, 'SHFE' if min_exch == 'SHF' else min_exch):
        prefix = f'{exch}|F|{prod}|'
        files = sorted(f for f in MIN_DIR.glob(f'{prefix}*.parquet'))
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


def _get_switches(day_file: Path) -> pd.DataFrame:
    """从日线文件提取切换表"""
    df = pd.read_parquet(day_file).sort_values('trading_day').reset_index(drop=True)
    mask = (
        df['adjustment_mul'].ne(df['adjustment_mul'].shift())
        | df['adjustment_add'].ne(df['adjustment_add'].shift())
    )
    if mask.iloc[0]:
        mask.iloc[0] = False
    sw = df.loc[mask, ['trading_day', 'instrument_id', 'adjustment_mul', 'adjustment_add']].copy()
    sw['trading_day'] = pd.to_datetime(sw['trading_day']).dt.date
    sw = sw[sw['trading_day'] >= MIN_DATE].reset_index(drop=True)

    # 添加窗口边界列（方便 Excel VLOOKUP）
    sw['window_start'] = sw['trading_day'].apply(lambda d: d - timedelta(days=WINDOW_DAYS))
    sw['window_end'] = sw['trading_day'].apply(lambda d: d + timedelta(days=WINDOW_DAYS))

    # 标记是否为首个切换（之前无主导合约）
    is_first_switch = [True] + [False] * (len(sw) - 1)
    sw.insert(0, 'is_first_switch', is_first_switch)

    return sw


def _export_one_switch(
    switch_row: pd.Series,
    prev_inst: str | None,
    inst_to_fname: dict[str, str],
    switches_df: pd.DataFrame,
    output_dir: Path,
    prod: str,
) -> Path:
    """为一个切换日导出 Excel"""
    switch_date = switch_row['trading_day']
    fname = f'{prod}_{switch_date.isoformat()}.xlsx'
    output_path = output_dir / fname

    wb = Workbook()
    # 移除默认 sheet
    wb.remove(wb.active)

    # Sheet 0: _SWITCHES（完整切换表）
    ws_sw = wb.create_sheet('_SWITCHES')
    for r in dataframe_to_rows(switches_df, index=False, header=True):
        ws_sw.append(r)

    # 写入前置合约（如果存在，且切换不是当前日期）
    # 当前切换日的合约一定导出
    instruments_to_export = {switch_row['instrument_id']}

    # 同时导出下一个切换的合约（如果存在）
    sw_idx = switches_df[switches_df['trading_day'] == switch_date].index[0]
    if sw_idx + 1 < len(switches_df):
        instruments_to_export.add(switches_df.iloc[sw_idx + 1]['instrument_id'])

    start = switch_date - timedelta(days=WINDOW_DAYS)
    end = switch_date + timedelta(days=WINDOW_DAYS)

    for inst in instruments_to_export:
        fn = inst_to_fname.get(inst)
        if fn is None:
            print(f"  [WARN] Missing min file for {inst}, skipping")
            continue

        dfm = pd.read_parquet(MIN_DIR / fn)
        dfm['trade_time'] = pd.to_datetime(dfm['trade_time'])
        mask = (dfm['trade_time'] >= pd.Timestamp(start)) & (dfm['trade_time'] <= pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
        df_win = dfm.loc[mask].copy()
        df_win = df_win.sort_values('trade_time').reset_index(drop=True)

        # 确保列顺序一致
        cols = ['trade_time', 'trading_day', 'instrument_id',
                'open_price', 'highest_price', 'lowest_price', 'close_price',
                'settlement_price', 'volume', 'turnover', 'open_interest',
                'pre_settlement_price', 'twap', 'vwap',
                'upper_limit_price', 'lower_limit_price']

        # 只保留存在的列
        cols = [c for c in cols if c in df_win.columns]
        df_win = df_win[cols]

        ws = wb.create_sheet(inst)
        for r in dataframe_to_rows(df_win, index=False, header=True):
            ws.append(r)

    wb.save(output_path)
    return output_path


def main():
    manifest = {}
    for prod, (day_exch, min_exch) in TOP_PRODUCTS.items():
        print(f"\n{'='*60}")
        print(f"Processing {prod} ({day_exch})...")

        day_file = _find_day_file(prod, day_exch)
        switches = _get_switches(day_file)
        print(f"  Switches: {len(switches)}")

        inst_to_fname = _find_min_files(prod, min_exch)
        print(f"  Min files: {len(inst_to_fname)}")

        output_dir = OUTPUT_BASE / prod
        output_dir.mkdir(parents=True, exist_ok=True)

        prod_manifest = []
        for idx, (_, row) in enumerate(switches.iterrows()):
            prev_inst = switches.iloc[idx - 1]['instrument_id'] if idx > 0 else None
            try:
                out_path = _export_one_switch(
                    row, prev_inst, inst_to_fname, switches, output_dir, prod
                )
                sw_date = row['trading_day'].isoformat()
                prod_manifest.append({
                    'switch_date': sw_date,
                    'instrument': row['instrument_id'],
                    'file': out_path.name,
                })
                print(f"  [{idx+1}/{len(switches)}] {sw_date} -> {out_path.name}")
            except Exception as e:
                print(f"  [{idx+1}/{len(switches)}] ERROR: {e}")
                prod_manifest.append({
                    'switch_date': row['trading_day'].isoformat(),
                    'instrument': row['instrument_id'],
                    'error': str(e),
                })

        manifest[prod] = {
            'day_exch': day_exch,
            'min_exch': min_exch,
            'switch_count': len(switches),
            'files': prod_manifest,
        }

    # 写 manifest
    manifest_path = OUTPUT_BASE / '_manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str, ensure_ascii=False))
    print(f"\n{'='*60}")
    print(f"Manifest: {manifest_path}")
    total_files = sum(len(m['files']) for m in manifest.values())
    print(f"Total files: {total_files}")


if __name__ == '__main__':
    main()
