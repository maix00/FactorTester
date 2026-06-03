"""
test_0_discover_products.py
----------------------------
自动扫描所有品种，按分钟数据覆盖范围内的主导合约切换次数降序排列，
取 TOP N 品种供 test_1 导出使用。

输出：模块级 PRODUCTS dict，key=品种代码，value=(day_exch, min_exch)
用法：
    from tests.calc.test_0_discover_products import TOP_PRODUCTS
"""

import pandas as pd
import re
from pathlib import Path
from datetime import date
from collections import defaultdict

from scripts.data_dir import DATA_DIR as _ROOT_DATA_DIR

DATA_DIR = Path(_ROOT_DATA_DIR)
DAY_DIR = DATA_DIR / 'main_dayk'
MIN_DIR = DATA_DIR / 'data_mink_product'
TOP_N = 8
MIN_DATE = date(2024, 1, 1)


def _discover() -> dict[str, tuple[str, str]]:
    """扫描所有品种，返回 TOP_N 个 (switch_count, prod, day_exch, min_exch)"""
    if not DAY_DIR.exists():
        raise FileNotFoundError(f"Day data dir not found: {DAY_DIR}")
    if not MIN_DIR.exists():
        raise FileNotFoundError(f"Min data dir not found: {MIN_DIR}")

    min_files = [f.name for f in MIN_DIR.glob('*.parquet')]
    min_prods = set()
    for fn in min_files:
        m = re.match(r'([^|]+)\|F\|([^|]+)\|', fn)
        if m:
            min_prods.add(m.group(2))

    results = []
    for day_file in sorted(DAY_DIR.glob('*.parquet')):
        prod = day_file.stem.split('.')[0]
        if prod not in min_prods:
            continue

        # 解析交易所（从文件名：RB.SHF.parquet → SHFE）
        EXCH_NORMALIZE = {'SHF': 'SHFE'}
        parts = day_file.stem.split('.')
        exch = parts[1] if len(parts) > 1 else None
        if not exch:
            continue
        exch = EXCH_NORMALIZE.get(exch, exch)

        df = pd.read_parquet(day_file).sort_values('trading_day').reset_index(drop=True)
        mask = (
            df['adjustment_mul'].ne(df['adjustment_mul'].shift())
            | df['adjustment_add'].ne(df['adjustment_add'].shift())
        )
        if mask.iloc[0]:
            mask.iloc[0] = False  # 第一个记录不算切换
        sw = df.loc[mask, ['trading_day', 'instrument_id', 'adjustment_mul', 'adjustment_add']].copy()
        sw['trading_day'] = pd.to_datetime(sw['trading_day']).dt.date
        sw = sw[sw['trading_day'] >= MIN_DATE].reset_index(drop=True)

        cnt = len(sw)
        if cnt == 0:
            continue

        # 确认分钟文件里的交易所（可能与日线文件不同）
        min_exch = exch
        min_prefix = f'{exch}|F|{prod}|'
        if not any(f.startswith(min_prefix) for f in min_files):
            for f in min_files:
                if f'|F|{prod}|' in f:
                    min_exch = f.split('|')[0]
                    break

        results.append((cnt, prod, exch, min_exch))

    results.sort(reverse=True)
    results = results[:TOP_N]

    out = {}
    for cnt, prod, day_exch, min_exch in results:
        out[prod] = (day_exch, min_exch)
        print(f"[test_0] {prod} ({day_exch}): {cnt} switches")

    return out


TOP_PRODUCTS: dict[str, tuple[str, str]] = _discover()


if __name__ == '__main__':
    print(f"\nTOP_PRODUCTS = {{")
    for prod, (de, me) in TOP_PRODUCTS.items():
        print(f"    {prod!r}: ({de!r}, {me!r}),")
    print(f"}}")
