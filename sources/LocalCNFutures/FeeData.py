"""
中国期货手续费率数据管理模块。

数据来源：http://openctp.cn/fees.html （每日实时）
本地存储：../data/fees/fees_YYYYMMDD.parquet（按日期存档）
         ../data/fees/fees_latest.parquet（最新一份，供快速读取）

字段说明（从 openctp 表格提取）：
  variety_code  : 品种代码（大写，如 RB、CU）
  exchange      : 交易所（SHFE/DCE/CZCE/CFFEX/INE/GFEX）
  variety_name  : 品种名称（中文）
  multiplier    : 合约乘数
  min_tick      : 最小变动价位
  open_ratio    : 开仓手续费率（按金额比例，小数）
  open_fixed    : 开仓手续费（按手，元）
  close_ratio   : 平仓手续费率
  close_fixed   : 平仓手续费（按手，元）
  closetoday_ratio : 平今手续费率
  closetoday_fixed : 平今手续费（按手，元）
  date          : 数据日期（YYYYMMDD 字符串）
"""

from __future__ import annotations

import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

# 本地存储目录（相对于项目根目录，即 Codes/）
_DATA_DIR = Path(__file__).parent.parent.parent.parent / 'data' / 'fees'
_LATEST_PATH = _DATA_DIR / 'fees_latest.parquet'
_URL = 'http://openctp.cn/fees.html'

# openctp 表格列顺序（根据实际页面，共 36 列）
# 交易所(0) 合约代码(1) 合约名称(2) 品种代码(3) 品种名称(4)
# 合约乘数(5) 最小变动(6)
# 开仓费率(7) 开仓/手(8)  平仓费率(9) 平仓/手(10)  平今费率(11) 平今/手(12)
# 多保证金率(13) 多保证金/手(14) 空保证金率(15) 空保证金/手(16)
# 现价(17) 最高(18) 最低(19) 成交量(20) 持仓量(21)
# ...派生字段(22-)
_COL_INDICES = {
    'exchange':          0,
    'contract_code':     1,
    'contract_name':     2,
    'variety_code':      3,
    'variety_name':      4,
    'multiplier':        5,
    'min_tick':          6,
    'open_ratio':        7,
    'open_fixed':        8,
    'close_ratio':       9,
    'close_fixed':       10,
    'closetoday_ratio':  11,
    'closetoday_fixed':  12,
    'volume':            20,
    'open_interest':     21,
}


def _fetch_raw() -> pd.DataFrame:
    """从 openctp 获取原始表格，返回所有合约行。"""
    tables = pd.read_html(_URL, flavor='html5lib')
    # 取最长的那张表（主数据表）
    df = max(tables, key=lambda t: len(t))
    return df


def _parse_raw(df: pd.DataFrame) -> pd.DataFrame:
    """从原始表格提取品种级费率（按品种代码去重，取主力合约行）。"""
    # 重命名列
    rename = {df.columns[v]: k for k, v in _COL_INDICES.items() if v < len(df.columns)}
    df = df.rename(columns=rename)

    keep = list(rename.values())
    df = df[keep].copy()

    # 类型转换
    for col in ['multiplier', 'min_tick', 'open_ratio', 'open_fixed', 'close_ratio', 'close_fixed',
                'closetoday_ratio', 'closetoday_fixed', 'volume', 'open_interest']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # 品种代码统一大写
    df['variety_code'] = df['variety_code'].astype(str).str.strip().str.upper()
    df['exchange'] = df['exchange'].astype(str).str.strip()
    df['variety_name'] = df['variety_name'].astype(str).str.strip()
    df['contract_code'] = df['contract_code'].astype(str).str.strip()

    # 去掉无效行
    df = df.dropna(subset=['variety_code', 'open_ratio'])
    df = df[df['variety_code'].str.len() > 0]

    # 按品种去重：取持仓量最大的合约（主力）
    df = df.sort_values('open_interest', ascending=False)
    df = df.drop_duplicates(subset=['variety_code'], keep='first')

    df = df.drop(columns=['contract_code', 'volume', 'open_interest'], errors='ignore')
    df = df.reset_index(drop=True)
    return df


def fetch_and_save(force: bool = False) -> pd.DataFrame:
    """
    检查本地是否已有今日数据；若无则从 openctp 抓取并保存。

    Parameters
    ----------
    force : 强制重新获取，即使本地已有今日数据

    Returns
    -------
    品种级费率 DataFrame
    """
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    today_str = date.today().strftime('%Y%m%d')
    daily_path = _DATA_DIR / f'fees_{today_str}.parquet'

    if not force and daily_path.exists():
        return pd.read_parquet(daily_path)

    print(f'[FeeData] 从 {_URL} 获取手续费率数据...')
    try:
        raw = _fetch_raw()
        df = _parse_raw(raw)
        df['date'] = today_str
        df.to_parquet(daily_path, index=False)
        df.to_parquet(_LATEST_PATH, index=False)
        print(f'[FeeData] 已保存 {len(df)} 个品种费率 → {daily_path}')
        return df
    except Exception as e:
        print(f'[FeeData] 获取失败: {e}')
        # 降级：使用最新本地数据
        return load_latest()


def load_latest() -> pd.DataFrame:
    """读取最新本地数据；若无则尝试下载。"""
    if _LATEST_PATH.exists():
        return pd.read_parquet(_LATEST_PATH)
    # 尝试找已有的日期文件
    files = sorted(_DATA_DIR.glob('fees_2*.parquet'), reverse=True)
    if files:
        df = pd.read_parquet(files[0])
        df.to_parquet(_LATEST_PATH, index=False)
        return df
    # 完全没有本地数据 → 下载
    return fetch_and_save(force=True)


def get_fee_map(use_closetoday: bool = False) -> dict[str, dict]:
    """
    返回品种代码 → 费率字典（单边，按金额比例）。

    Parameters
    ----------
    use_closetoday : 是否使用平今费率（替代平仓费率）

    Returns
    -------
    {
        'rb': {'open_ratio': 0.0001, 'open_fixed': 0.01,
               'close_ratio': 0.0001, 'close_fixed': 0.01,
               'multiplier': 10, 'variety_name': '螺纹钢',
               'exchange': 'SHFE'},
        ...
    }
    """
    df = load_latest()
    result: dict = {}
    for _, row in df.iterrows():
        code = str(row['variety_code']).upper()
        close_ratio = float(row['closetoday_ratio'] if use_closetoday else row['close_ratio']) or 0.0
        close_fixed = float(row['closetoday_fixed'] if use_closetoday else row['close_fixed']) or 0.0
        result[code] = {
            'open_ratio':  float(row['open_ratio'])  if pd.notna(row['open_ratio'])  else 0.0,
            'open_fixed':  float(row['open_fixed'])  if pd.notna(row['open_fixed'])  else 0.0,
            'close_ratio': close_ratio,
            'close_fixed': close_fixed,
            'multiplier':  float(row['multiplier'])  if pd.notna(row['multiplier'])  else 1.0,
            'variety_name': str(row.get('variety_name', '')),
            'exchange':     str(row.get('exchange', '')),
        }
    return result


def ensure_today_data() -> bool:
    """
    确保今日费率数据存在（服务启动 / 请求时调用）。
    返回 True 表示已有或成功获取，False 表示获取失败但有历史数据兜底。
    """
    today_str = date.today().strftime('%Y%m%d')
    daily_path = _DATA_DIR / f'fees_{today_str}.parquet'
    if daily_path.exists():
        return True
    try:
        fetch_and_save()
        return True
    except Exception:
        return _LATEST_PATH.exists() or any(_DATA_DIR.glob('fees_2*.parquet'))


def get_table_for_display() -> list[dict]:
    """
    返回供前端展示的品种费率列表（所有品种，含计算字段）。
    每项为：
    {
        variety_code, variety_name, exchange, multiplier,
        open_ratio, open_fixed, close_ratio, close_fixed,
        closetoday_ratio, closetoday_fixed, date
    }
    """
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    # 优先使用今日数据，否则用最新
    today_str = date.today().strftime('%Y%m%d')
    daily_path = _DATA_DIR / f'fees_{today_str}.parquet'
    if not daily_path.exists():
        fetch_and_save()
    df = load_latest()
    cols = ['variety_code', 'variety_name', 'exchange', 'multiplier', 'min_tick',
            'open_ratio', 'open_fixed', 'close_ratio', 'close_fixed',
            'closetoday_ratio', 'closetoday_fixed', 'date']
    df = df[[c for c in cols if c in df.columns]].copy()
    # NaN → 0
    for col in df.select_dtypes(include='number').columns:
        df[col] = df[col].fillna(0)
    df = df.sort_values('variety_code')
    return df.to_dict(orient='records')
