"""
test_1_export_truncated.py
--------------------------
从 test_0 自动获取 TOP N 品种，导出截断数据到 Excel。

每个品种 → 一个 Excel 文件：data/test/test_1/{prod}.xlsx
- Sheet _SWITCHES：该品种完整切换表
- Sheet {instrument_id}：最近一次切换的合约 ±30 天内的分钟数据
- Sheet {instrument_id}（第二个）：第二近的切换合约 ±30 天内的分钟数据
- ... 依次排列，最多最近 N 次切换

Output: data/test/test_1/{prod}.xlsx + _manifest.json
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
OUTPUT_BASE = DATA_DIR / 'test' / 'test_1'
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


def _export_product(
    prod: str,
    switches: pd.DataFrame,
    inst_to_fname: dict[str, str],
    output_dir: Path,
) -> Path:
    """为一个品种导出 Excel：Sheet1=切换表，Sheet2/3/...=最近切换的合约±30天数据"""
    output_path = output_dir / f'{prod}.xlsx'

    wb = Workbook()
    # 移除默认 sheet
    wb.remove(wb.active)

    # Sheet 1: _SWITCHES（完整切换表）
    ws_sw = wb.create_sheet('_SWITCHES')
    for r in dataframe_to_rows(switches, index=False, header=True):
        ws_sw.append(r)

    # 从最近一次切换开始，向前取切换合约，每个合约导出前后 WINDOW_DAYS 数据
    exported_count = 0
    max_sheets = min(len(switches), 5)  # 最多导最近 5 次切换

    # switches 按 trading_day 降序排列（最近在前）
    switches_desc = switches.sort_values('trading_day', ascending=False)

    for _, sw in switches_desc.iterrows():
        if exported_count >= max_sheets:
            break

        inst = sw['instrument_id']
        switch_date = sw['trading_day']

        fn = inst_to_fname.get(inst)
        if fn is None:
            print(f"  [WARN] Missing min file for {inst}, skipping")
            continue

        start = switch_date - timedelta(days=WINDOW_DAYS)
        end = switch_date + timedelta(days=WINDOW_DAYS)

        dfm = pd.read_parquet(MIN_DIR / fn)
        dfm['trade_time'] = pd.to_datetime(dfm['trade_time'])
        mask = (dfm['trade_time'] >= pd.Timestamp(start)) & (dfm['trade_time'] <= pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
        df_win = dfm.loc[mask].copy()
        df_win = df_win.sort_values('trade_time').reset_index(drop=True)

        if len(df_win) == 0:
            print(f"  [SKIP] {inst} ({switch_date}) has 0 rows")
            continue

        cols = ['trade_time', 'trading_day', 'instrument_id',
                'open_price', 'highest_price', 'lowest_price', 'close_price',
                'settlement_price', 'volume', 'turnover', 'open_interest',
                'pre_settlement_price', 'twap', 'vwap',
                'upper_limit_price', 'lower_limit_price']
        cols = [c for c in cols if c in df_win.columns]
        df_win = df_win[cols]

        # Sheet 名用合约代码 + 切换日期
        sheet_name = f'{inst}'
        ws = wb.create_sheet(sheet_name)
        for r in dataframe_to_rows(df_win, index=False, header=True):
            ws.append(r)

        exported_count += 1
        print(f"  [{exported_count}] {inst} ({switch_date}): {len(df_win)} rows")

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

        try:
            out_path = _export_product(prod, switches, inst_to_fname, output_dir)
            # 收集切换信息
            switches_desc = switches.sort_values('trading_day', ascending=False)
            sheet_list = []
            max_sheets = min(len(switches_desc), 5)
            for i in range(max_sheets):
                sw = switches_desc.iloc[i]
                sheet_list.append({
                    'switch_date': sw['trading_day'].isoformat(),
                    'instrument': sw['instrument_id'],
                    'sheet': sw['instrument_id'],
                })
            manifest[prod] = {
                'day_exch': day_exch,
                'min_exch': min_exch,
                'switch_count': len(switches),
                'file': out_path.name,
                'sheets': sheet_list,
            }
            print(f"  -> {out_path.name}")
        except Exception as e:
            print(f"  ERROR: {e}")
            manifest[prod] = {
                'day_exch': day_exch,
                'min_exch': min_exch,
                'switch_count': len(switches),
                'error': str(e),
            }

    # 写 manifest
    manifest_path = OUTPUT_BASE / '_manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str, ensure_ascii=False))
    print(f"\n{'='*60}")
    print(f"Manifest: {manifest_path}")
    total_files = sum(1 for m in manifest.values() if 'file' in m)
    print(f"Total files: {total_files}")


if __name__ == '__main__':
    main()
