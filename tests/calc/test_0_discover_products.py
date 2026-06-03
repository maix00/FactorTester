"""
test_0_discover_products.py
----------------------------
扫描所有品种，按该品种分钟数据实际覆盖范围内的主导合约切换次数降序排列，
取 TOP N 品种供 test_1 导出使用。

输出：模块级 TOP_PRODUCTS dict，key=品种代码，value=(day_exch, min_exch)
用法：
    from tests.calc.test_0_discover_products import TOP_PRODUCTS
"""

import pandas as pd
import re
from pathlib import Path

from scripts.data_dir import DATA_DIR as _ROOT_DATA_DIR

DATA_DIR = Path(_ROOT_DATA_DIR)
DAY_DIR = DATA_DIR / 'main_dayk'
MIN_DIR = DATA_DIR / 'data_mink_product'
TOP_N = 8


def _discover() -> dict[str, tuple[str, str]]:
    """扫描所有品种，返回 TOP_N 个 (switch_count, prod, day_exch, min_exch)"""
    if not DAY_DIR.exists():
        raise FileNotFoundError(f"Day data dir not found: {DAY_DIR}")
    if not MIN_DIR.exists():
        raise FileNotFoundError(f"Min data dir not found: {MIN_DIR}")

    # 收集所有分钟数据品种 + 预计算每个品种的时间范围
    min_prods: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    min_files = []
    for fn in MIN_DIR.glob('*.parquet'):
        m = re.match(r'([^|]+)\|F\|([^|]+)\|', fn.name)
        if not m:
            continue
        prod = m.group(2)
        min_files.append(fn.name)
        df = pd.read_parquet(fn)
        t_min = pd.Timestamp(df['trade_time'].min())
        t_max = pd.Timestamp(df['trade_time'].max())
        if prod not in min_prods:
            min_prods[prod] = (t_min, t_max)
        else:
            prev = min_prods[prod]
            min_prods[prod] = (min(prev[0], t_min), max(prev[1], t_max))

    EXCH_NORMALIZE = {'SHF': 'SHFE'}
    results = []

    for day_file in sorted(DAY_DIR.glob('*.parquet')):
        prod = day_file.stem.split('.')[0]
        if prod not in min_prods:
            continue

        # 解析交易所
        parts = day_file.stem.split('.')
        exch = parts[1] if len(parts) > 1 else None
        if not exch:
            continue
        exch = EXCH_NORMALIZE.get(exch, exch)

        # 该品种分钟数据的实际覆盖范围
        min_data_start, min_data_end = min_prods[prod]

        df = pd.read_parquet(day_file).sort_values('trading_day').reset_index(drop=True)
        mask = (
            df['adjustment_mul'].ne(df['adjustment_mul'].shift())
            | df['adjustment_add'].ne(df['adjustment_add'].shift())
        )
        if mask.iloc[0]:
            mask.iloc[0] = False
        sw = df.loc[mask, ['trading_day', 'instrument_id', 'adjustment_mul', 'adjustment_add']].copy()
        sw['trading_day'] = pd.to_datetime(sw['trading_day']).dt.date

        # 只看在分钟数据覆盖范围内的切换点
        # 切换发生在 trading_day，但数据覆盖从 min_data_start 到 min_data_end
        sw = sw[(sw['trading_day'] >= min_data_start.date()) & (sw['trading_day'] <= min_data_end.date())].reset_index(drop=True)

        cnt = len(sw)
        if cnt == 0:
            continue

        # 确认分钟文件里的交易所
        min_exch = exch
        min_prefix = f'{exch}|F|{prod}|'
        if not any(f.startswith(min_prefix) for f in min_files):
            for f in min_files:
                if f'|F|{prod}|' in f:
                    min_exch = f.split('|')[0]
                    break

        results.append((cnt, prod, exch, min_exch, min_data_start, min_data_end))

    results.sort(reverse=True)
    results = results[:TOP_N]

    out = {}
    for cnt, prod, day_exch, min_exch, d_min, d_max in results:
        out[prod] = (day_exch, min_exch)
        print(f"[test_0] {prod} ({day_exch}): {cnt} switches in {d_min.date()} ~ {d_max.date()}")

    return out


TOP_PRODUCTS: dict[str, tuple[str, str]] = _discover()


if __name__ == '__main__':
    print(f"\nTOP_PRODUCTS = {{")
    for prod, (de, me) in TOP_PRODUCTS.items():
        print(f"    {prod!r}: ({de!r}, {me!r}),")
    print(f"}}")
