"""
中国期货手续费率数据管理模块。

数据来源：http://openctp.cn/fees.html （每日实时）
本地存储：../data/fees/fees_YYYYMMDD.parquet（按日期存档）
         ../data/fees/fees_latest.parquet（最新一份，供快速读取）

字段说明（从 openctp 表格提取）：
  contract_code : 合约代码（如 rb2610）
  contract_name : 合约名称
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
  long_margin_ratio  : 多头保证金率
  long_margin_fixed  : 多头保证金（按手，元）
  short_margin_ratio : 空头保证金率
  short_margin_fixed : 空头保证金（按手，元）
  date          : 数据日期（YYYYMMDD 字符串）
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from scripts.data_dir import DATA_DIR

# 本地存储目录
_DATA_DIR = Path(DATA_DIR) / 'fees'
_LATEST_PATH = _DATA_DIR / 'fees_latest.parquet'
_CONTRACT_LATEST_PATH = _DATA_DIR / 'fees_contracts_latest.parquet'
_URL = 'http://openctp.cn/fees.html'

# openctp 表格列顺序（根据实际页面，共 36 列）
# 交易所(0) 合约代码(1) 合约名称(2) 品种代码(3) 品种名称(4)
# 合约乘数(5) 最小变动(6)
# 开仓费率(7) 开仓/手(8)  平仓费率(9) 平仓/手(10)  平今费率(11) 平今/手(12)
# 多保证金率(13) 多保证金/手(14) 空保证金率(15) 空保证金/手(16)
# 现价(17) 最高(18) 最低(19) 成交量(20) 持仓量(21)
# 派生字段: 1手开仓费用(22) 1手平仓费用(23) 1手平今费用(24) ...
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
    'long_margin_ratio': 13,
    'long_margin_fixed': 14,
    'short_margin_ratio': 15,
    'short_margin_fixed': 16,
    'price':             17,   # 上日结算价
    'volume':            20,
    'open_interest':     21,
    # OpenCTP 派生列（一手手续费 = price×multiplier×ratio + fixed）
    'open_total_fee':    22,   # 1手开仓费用
    'close_total_fee':   23,   # 1手平仓费用
    'closetoday_total_fee': 24,  # 1手平今费用
}

_NUMERIC_COLS = [
    'multiplier', 'min_tick',
    'open_ratio', 'open_fixed',
    'close_ratio', 'close_fixed',
    'closetoday_ratio', 'closetoday_fixed',
    'long_margin_ratio', 'long_margin_fixed',
    'short_margin_ratio', 'short_margin_fixed',
    'price',
    'volume', 'open_interest',
    'open_total_fee', 'close_total_fee', 'closetoday_total_fee',
]

_OPTIONAL_NUMERIC_COLS = [
    'long_margin_ratio', 'long_margin_fixed',
    'short_margin_ratio', 'short_margin_fixed',
]

_CONTRACT_ROW_DROP_COLS: list[str] = []
_VARIETY_ROW_DROP_COLS = ['volume', 'open_interest']


def _with_optional_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in _OPTIONAL_NUMERIC_COLS:
        if col not in df.columns:
            df[col] = 0.0
    return df


def _normalise_contract_code(value: Any) -> str:
    text = str(value or '').strip().upper()
    text = text.split('.')[0]
    text = re.sub(r'[^A-Z0-9]', '', text)
    return text


def _date_str(value: Any | None = None) -> str:
    if value is None:
        return date.today().strftime('%Y%m%d')
    return pd.Timestamp(value).strftime('%Y%m%d')


def _daily_path(date_str: str) -> Path:
    return _DATA_DIR / f'fees_{date_str}.parquet'


def _contract_daily_path(date_str: str) -> Path:
    return _DATA_DIR / f'fees_contracts_{date_str}.parquet'


def _available_contract_snapshot_dates() -> list[str]:
    if not _DATA_DIR.exists():
        return []
    dates: list[str] = []
    for path in _DATA_DIR.glob('fees_contracts_2*.parquet'):
        match = re.fullmatch(r'fees_contracts_(\d{8})\.parquet', path.name)
        if match:
            dates.append(match.group(1))
    return sorted(dates)


def _contract_asof_path(target: str) -> tuple[Path | None, str | None]:
    dates = _available_contract_snapshot_dates()
    candidates = [snapshot_date for snapshot_date in dates if snapshot_date <= target]
    if not candidates:
        return None, None
    snapshot_date = candidates[-1]
    return _contract_daily_path(snapshot_date), snapshot_date


def _fetch_raw() -> pd.DataFrame:
    """从 openctp 获取原始表格，返回所有合约行。"""
    tables = pd.read_html(_URL, flavor='html5lib')
    # 取最长的那张表（主数据表）
    df = max(tables, key=lambda t: len(t))
    return df


def _parse_contract_rows(df: pd.DataFrame) -> pd.DataFrame:
    """从原始表格提取合约级费率行。

    OpenCTP 给的是某个快照日期下的合约行。该函数不按品种去重，用于未来
    ``Futures + trading_day -> 主力 FuturesContract -> 当日合约费率`` 的查询。
    """
    # 重命名列
    rename = {df.columns[v]: k for k, v in _COL_INDICES.items() if v < len(df.columns)}
    df = df.rename(columns=rename)

    keep = list(rename.values())
    df = df[keep].copy()

    # 类型转换
    for col in [col for col in _NUMERIC_COLS if col in df.columns]:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # 品种代码统一大写
    df['variety_code'] = df['variety_code'].astype(str).str.strip().str.upper()
    df['exchange'] = df['exchange'].astype(str).str.strip()
    df['variety_name'] = df['variety_name'].astype(str).str.strip()
    df['contract_code'] = df['contract_code'].astype(str).str.strip()
    df['contract_name'] = df['contract_name'].astype(str).str.strip()
    df['contract_key'] = df['contract_code'].map(_normalise_contract_code)

    # 去掉无效行
    df = df.dropna(subset=['variety_code', 'open_ratio'])
    df = df[df['variety_code'].str.len() > 0]
    df = df[df['contract_key'].str.len() > 0]

    # 计算有效费率并原地覆盖原始列
    # effective_ratio = ratio × total_fee / (total_fee - fixed)
    # 当 fixed=0 或 分母<=0 时，有效费率 = 原费率；当 fixed>0 时，有效费率 > 原费率
    for kind, ratio_col, fixed_col, fee_col in [
        ('open', 'open_ratio', 'open_fixed', 'open_total_fee'),
        ('close', 'close_ratio', 'close_fixed', 'close_total_fee'),
        ('closetoday', 'closetoday_ratio', 'closetoday_fixed', 'closetoday_total_fee'),
    ]:
        if fee_col not in df.columns or ratio_col not in df.columns:
            continue
        # 保留原始费率 → xxx_original_ratio
        original_col = f'{kind}_original_ratio'
        df[original_col] = df[ratio_col].copy()
        fee = df[fee_col].fillna(0.0)
        ratio = df[ratio_col].fillna(0.0)
        fixed = df[fixed_col].fillna(0.0) if fixed_col in df.columns else 0.0
        denominator = fee - fixed
        safe = denominator > 1e-12
        ratio[safe] = ratio[safe] * fee[safe] / denominator[safe]
        df[ratio_col] = ratio

    df = df.drop(columns=_CONTRACT_ROW_DROP_COLS, errors='ignore')
    df = df.reset_index(drop=True)
    return _with_optional_columns(df)


def _parse_raw(df: pd.DataFrame) -> pd.DataFrame:
    """从原始表格提取品种级展示费率（按品种代码去重，取持仓量最大的代表合约行）。

    注意：这是给前端默认展示和静态品种费率兜底使用的品种级近似，不应用作
    历史回测中的真实合约费率。历史回测应结合 Futures.roller_info 在每个交易日
    找到主力 FuturesContract，再查对应日期快照里的合约级费率。
    """
    df = _parse_contract_rows(df)

    # 按品种去重：取持仓量最大的合约（主力）
    if 'open_interest' in df.columns:
        df = df.sort_values('open_interest', ascending=False)
    df = df.drop_duplicates(subset=['variety_code'], keep='first')

    df = df.rename(columns={'contract_code': 'representative_contract_code'})
    df = df.drop(columns=_VARIETY_ROW_DROP_COLS, errors='ignore')
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
    today_str = _date_str()
    daily_path = _daily_path(today_str)
    contract_daily_path = _contract_daily_path(today_str)

    if not force and daily_path.exists():
        cached = pd.read_parquet(daily_path)
        if (
            all(col in cached.columns for col in _OPTIONAL_NUMERIC_COLS)
            and contract_daily_path.exists()
        ):
            return cached

    print(f'[FeeData] 从 {_URL} 获取手续费率数据...')
    try:
        raw = _fetch_raw()
        contract_df = _parse_contract_rows(raw)
        contract_df['date'] = today_str
        df = _with_optional_columns(_parse_raw(raw))
        df['date'] = today_str
        contract_df.to_parquet(contract_daily_path, index=False)
        contract_df.to_parquet(_CONTRACT_LATEST_PATH, index=False)
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
        return _with_optional_columns(pd.read_parquet(_LATEST_PATH))
    # 尝试找已有的日期文件
    files = sorted(_DATA_DIR.glob('fees_2*.parquet'), reverse=True)
    if files:
        df = pd.read_parquet(files[0])
        df.to_parquet(_LATEST_PATH, index=False)
        return _with_optional_columns(df)
    # 完全没有本地数据 → 下载
    return fetch_and_save(force=True)


def load_contract_rows_for_date(
    trading_day: Any | None = None,
    *,
    allow_latest_fallback: bool = True,
) -> pd.DataFrame:
    """读取某日 OpenCTP 合约级费率快照。

    ``trading_day`` 对应的是回测交易日。若没有保存该日期的 OpenCTP 快照，
    默认使用 ``<= trading_day`` 的最近快照向前填充；若交易日早于所有快照，
    再静默使用最新快照推测历史费率，并在返回 DataFrame 的 ``attrs`` 中
    标记 ``fee_source='latest_inferred'``，供接口提示用户。
    """
    target = _date_str(trading_day)
    asof_path, source_date = _contract_asof_path(target)
    if asof_path is not None and source_date is not None:
        df = _with_optional_columns(pd.read_parquet(asof_path))
        df.attrs['fee_source'] = 'historical_snapshot' if source_date == target else 'historical_forward_fill'
        df.attrs['fee_source_date'] = source_date
        df.attrs['requested_fee_date'] = target
        return df
    if allow_latest_fallback and _CONTRACT_LATEST_PATH.exists():
        df = _with_optional_columns(pd.read_parquet(_CONTRACT_LATEST_PATH))
        df.attrs['fee_source'] = 'latest_inferred'
        df.attrs['requested_fee_date'] = target
        if 'date' in df.columns and not df.empty:
            df.attrs['fee_source_date'] = str(df['date'].iloc[0])
        return df
    raise FileNotFoundError(f"未找到 {target} 或更早的合约级费率快照")


def get_contract_fee_row(
    contract_code: Any,
    trading_day: Any | None = None,
    *,
    allow_latest_fallback: bool = True,
) -> Optional[pd.Series]:
    """按具体合约代码读取某日费率行。"""
    contract_key = _normalise_contract_code(contract_code)
    if not contract_key:
        return None
    df = load_contract_rows_for_date(
        trading_day,
        allow_latest_fallback=allow_latest_fallback,
    )
    match = df[df['contract_key'] == contract_key]
    if match.empty:
        return None
    return match.iloc[0]


def get_main_contract_fee_row(
    future: Any,
    trading_day: Any,
    *,
    allow_latest_fallback: bool = True,
) -> Optional[pd.Series]:
    """按 Futures 在交易日对应的主力 FuturesContract 查询合约费率。

    ``future`` 必须提供 ``get_contract_row_from_trading_day``。这里故意返回
    合约级快照行，而不是品种级费率，避免把 Futures 与 FuturesContract 混用。
    """
    if not hasattr(future, 'get_contract_row_from_trading_day'):
        return None
    roller_row = future.get_contract_row_from_trading_day(trading_day)
    if roller_row is None:
        return None
    for key in ('CONTRACT_PATCHED', 'CONTRACT', 'CONTRACT_UID'):
        fee_row = get_contract_fee_row(
            roller_row.get(key),
            trading_day,
            allow_latest_fallback=allow_latest_fallback,
        )
        if fee_row is not None:
            return fee_row
    return None


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
            'min_tick':    float(row.get('min_tick', 0.0)) if pd.notna(row.get('min_tick', 0.0)) else 0.0,
            'long_margin_ratio':  float(row.get('long_margin_ratio', 0.0)) if pd.notna(row.get('long_margin_ratio', 0.0)) else 0.0,
            'long_margin_fixed':  float(row.get('long_margin_fixed', 0.0)) if pd.notna(row.get('long_margin_fixed', 0.0)) else 0.0,
            'short_margin_ratio': float(row.get('short_margin_ratio', 0.0)) if pd.notna(row.get('short_margin_ratio', 0.0)) else 0.0,
            'short_margin_fixed': float(row.get('short_margin_fixed', 0.0)) if pd.notna(row.get('short_margin_fixed', 0.0)) else 0.0,
            'variety_name': str(row.get('variety_name', '')),
            'exchange':     str(row.get('exchange', '')),
        }
    return result


def ensure_today_data() -> bool:
    """
    确保今日费率数据存在（服务启动 / 请求时调用）。
    返回 True 表示已有或成功获取，False 表示获取失败但有历史数据兜底。
    """
    today_str = _date_str()
    daily_path = _daily_path(today_str)
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
    today_str = _date_str()
    daily_path = _daily_path(today_str)
    if not daily_path.exists():
        fetch_and_save()
    df = load_latest()
    df = _with_optional_columns(df)
    cols = ['variety_code', 'variety_name', 'exchange', 'multiplier', 'min_tick',
            'open_ratio', 'open_fixed', 'close_ratio', 'close_fixed',
            'closetoday_ratio', 'closetoday_fixed',
            'long_margin_ratio', 'long_margin_fixed',
            'short_margin_ratio', 'short_margin_fixed',
            'date']
    df = df[[c for c in cols if c in df.columns]].copy()
    # NaN → 0
    for col in df.select_dtypes(include='number').columns:
        df[col] = df[col].fillna(0)
    df = df.sort_values('variety_code')
    return df.to_dict(orient='records')
