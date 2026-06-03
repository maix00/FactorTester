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
    """为一个品种导出 Excel：Sheet1=切换表，Sheet2/3/...=各合约去重合并后的±30天数据
    
    同一合约可能出现在多个切换日，取该合约的最大跨度（min_start ~ max_end），
    再各扩展 WINDOW_DAYS，合并为一个 sheet。
    """
    output_path = output_dir / f'{prod}.xlsx'

    wb = Workbook()
    wb.remove(wb.active)

    # Sheet 1: _SWITCHES（完整切换表）
    ws_sw = wb.create_sheet('_SWITCHES')
    for r in dataframe_to_rows(switches, index=False, header=True):
        ws_sw.append(r)

    # 对每个 instrument_id 取最大时间跨度
    inst_spans: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    for _, sw in switches.iterrows():
        inst = sw['instrument_id']
        switch_date = sw['trading_day']
        start = pd.Timestamp(switch_date - timedelta(days=WINDOW_DAYS))
        end = pd.Timestamp(switch_date + timedelta(days=WINDOW_DAYS))
        if inst not in inst_spans:
            inst_spans[inst] = (start, end)
        else:
            prev_start, prev_end = inst_spans[inst]
            inst_spans[inst] = (min(prev_start, start), max(prev_end, end))

    # 找出每个合约最近一次切换日期，用于排序
    inst_last_switch: dict[str, date] = {}
    for _, sw in switches.iterrows():
        inst = sw['instrument_id']
        sd = sw['trading_day']
        if inst not in inst_last_switch or sd > inst_last_switch[inst]:
            inst_last_switch[inst] = sd

    # 按最近切换日期降序排序（最近合约在前）
    sorted_insts = sorted(inst_spans.keys(), key=lambda x: inst_last_switch[x], reverse=True)

    # 最多导最近 5 个合约
    max_sheets = min(len(sorted_insts), 5)
    exported_count = 0

    for inst in sorted_insts:
        if exported_count >= max_sheets:
            break

        fn = inst_to_fname.get(inst)
        if fn is None:
            print(f"  [WARN] Missing min file for {inst}, skipping")
            continue

        start_ts, end_ts = inst_spans[inst]
        # 把 end 扩展到当天结束
        end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

        dfm = pd.read_parquet(MIN_DIR / fn)
        dfm['trade_time'] = pd.to_datetime(dfm['trade_time'])
        mask = (dfm['trade_time'] >= start_ts) & (dfm['trade_time'] <= end_ts)
        df_win = dfm.loc[mask].copy()
        df_win = df_win.sort_values('trade_time').reset_index(drop=True)

        if len(df_win) == 0:
            print(f"  [SKIP] {inst} has 0 rows in merged span")
            continue

        cols = ['trade_time', 'trading_day', 'instrument_id',
                'open_price', 'highest_price', 'lowest_price', 'close_price',
                'settlement_price', 'volume', 'turnover', 'open_interest',
                'pre_settlement_price', 'twap', 'vwap',
                'upper_limit_price', 'lower_limit_price']
        cols = [c for c in cols if c in df_win.columns]
        df_win = df_win[cols]

        sheet_name = f'{inst}'
        ws = wb.create_sheet(sheet_name)
        for r in dataframe_to_rows(df_win, index=False, header=True):
            ws.append(r)

        exported_count += 1
        span_start = start_ts.strftime('%Y-%m-%d')
        span_end = end_ts.strftime('%Y-%m-%d')
        print(f"  [{exported_count}] {inst}: {len(df_win)} rows ({span_start} ~ {span_end})")

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
            # 收集 sheet 信息（和 _export_product 中排序一致）
            inst_last = {}
            for _, sw in switches.iterrows():
                inst = sw['instrument_id']
                sd = sw['trading_day']
                if inst not in inst_last or sd > inst_last[inst]:
                    inst_last[inst] = sd
            sorted_insts = sorted(inst_last.keys(), key=lambda x: inst_last[x], reverse=True)[:5]
            sheet_list = [{'instrument': inst, 'last_switch': inst_last[inst].isoformat()} for inst in sorted_insts]
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
