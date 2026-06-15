from typing import Any, Dict, List, Optional, Tuple, cast
import pandas as pd
import os
from pathlib import Path
from tools.products.Futures import Futures, FuturesContract
from tools import DataColumn
from scripts.data_dir import DATA_DIR

_data = pd.read_csv(os.path.join(DATA_DIR, 'sectors.csv'))
data_dir_min = os.path.join(DATA_DIR, 'main_mink')
data_path_day = os.path.join(DATA_DIR, 'main_series_adjusted.parquet')
data_dir_day = os.path.join(DATA_DIR, 'main_dayk')
data_type = 'parquet'

file_list_min = [
    os.path.join(data_dir_min, f)
    for f in os.listdir(data_dir_min)
    if f.endswith('.' + data_type) and '_S' not in f and '-S' not in f
]
file_list_day = [
    os.path.join(data_dir_day, f)
    for f in os.listdir(data_dir_day)
    if f.endswith('.' + data_type) and '_S' not in f and '-S' not in f
]
DataColumnMapping = {
    DataColumn.OPEN: 'open_price',
    DataColumn.HIGH: 'highest_price',
    DataColumn.LOW: 'lowest_price',
    DataColumn.CLOSE: 'close_price',
    DataColumn.VOLUME: 'volume',
    DataColumn.TURNOVER: 'turnover',
    DataColumn.OPEN_INTEREST: 'open_interest',
    DataColumn.TIME_COL_DAY: 'trading_day',
    DataColumn.TIME_COL_MIN: 'trade_time',
    DataColumn.TIMESTAMP: 'trade_timestamp',
    DataColumn.TWAP: 'twap',
    DataColumn.VWAP: 'vwap',
    DataColumn.SETTLEMENT_PRICE: 'settlement_price',
    DataColumn.ADJUSTMENT_MUL: 'adjustment_mul',
    DataColumn.ADJUSTMENT_ADD: 'adjustment_add',
    DataColumn.UPPER_LIMIT_PRICE: 'upper_limit_price',
    DataColumn.LOWER_LIMIT_PRICE: 'lower_limit_price',
    DataColumn.PRE_SETTLEMENT_PRICE: 'pre_settlement_price',
    DataColumn.OPEN_ADJUSTED: 'open_price_adjusted',
    DataColumn.HIGH_ADJUSTED: 'highest_price_adjusted',
    DataColumn.LOW_ADJUSTED: 'lowest_price_adjusted',
    DataColumn.CLOSE_ADJUSTED: 'close_price_adjusted',
    DataColumn.ADJUST_SUFFIX: '_adjusted',
    DataColumn.PRODUCT_NAME: 'unique_instrument_id',
}

exchange_map = {
    "DCE": "DCE",
    "CZCE": "CZC",
    "INE": "INE",
    "SHFE": "SHF",
    "CFFEX": "CFE",
    "GFEX": "GFE"
}

exchange_map_reversed = {v: k for k, v in exchange_map.items()}
datacolumn_map_reversed = {v: k for k, v in DataColumnMapping.items()}

code_col_name = '品种代码'
variety_col_name = '合约标的'
category_col_name = '类别'
exchange_col_name = '交易所'
exchange_code_col_name = '交易所代码'
night_time_col_name = '夜盘时间'
day_time_col_name = '日盘时间'
version_col_name = '版本'
highest_version_col_name = '最高版本'
enddate_col_name = '标准合约终止交易日'

name_code_version_dict = {}
contract_mapping_path = os.path.join(DATA_DIR, 'wind_mapping.parquet')
_CNFUTURES_BY_NAME: Dict[str, "CNFutures"] = {}
_CNFUTURES_CONTRACT_TO_PRODUCT_BY_PATH: Dict[str, Dict[str, str]] = {}
_CNFUTURES_PRODUCT_TO_CONTRACTS_BY_PATH: Dict[str, Dict[str, List[str]]] = {}


def _infer_unique_version(code: str, exchange_short: Optional[str] = None) -> Optional[str]:
    """Infer version when a product has exactly one version in metadata."""
    df = _data[_data[code_col_name].astype(str) == str(code)]
    if exchange_short is not None:
        exch = exchange_map_reversed.get(exchange_short, exchange_short)
        df = df[df[exchange_code_col_name].astype(str) == str(exch)]
    versions = sorted(set(pd.Series(df[version_col_name]).dropna().astype(str)))
    return versions[0] if len(versions) == 1 else None

def get_by_code_and_version(code: str, version: Optional[str], name: str) -> str | None:
    if version is None:
        return None
    if name not in name_code_version_dict:
        name_code_version_dict[name] = {
            (str(row[code_col_name]), str(row[version_col_name])): str(row[name])
            for _, row in _data.iterrows()
        }
    return name_code_version_dict[name].get((code, version))


def _patch_czc_contract_decade(row: pd.Series) -> Optional[str]:
    contract = row.get('CONTRACT')
    if not isinstance(contract, str):
        return None
    if not contract.endswith('CZC'):
        return contract
    enddate = row.get('ENDDATE')
    if pd.isna(enddate):
        return None
    digits = ''.join(filter(str.isdigit, contract))
    if len(digits) == 4:
        return contract
    if len(digits) != 3:
        return None

    end_str = pd.Timestamp(enddate).strftime('%Y%m%d')
    next_two = str(int(end_str[2:4]) + 1).zfill(2)
    decade = end_str[2] if digits[0] == end_str[3] else (next_two[0] if digits[0] == next_two[-1] else None)
    return contract.replace(digits, decade + digits) if decade else None


def _contract_to_uid(contract: Optional[str]) -> Optional[str]:
    if not isinstance(contract, str) or '.' not in contract:
        return None
    product_month, exchange = contract.split('.')
    first_digit = next((i for i, c in enumerate(product_month) if c.isdigit()), len(product_month))
    reverse_exchange = {v: k for k, v in exchange_map.items()}
    return f"{reverse_exchange.get(exchange, exchange)}|F|{product_month[:first_digit]}|{product_month[first_digit:]}"


def _cn_futures_contract_maps(path: Optional[str] = None) -> tuple[Dict[str, str], Dict[str, List[str]]]:
    path = path or contract_mapping_path
    if path not in _CNFUTURES_CONTRACT_TO_PRODUCT_BY_PATH:
        mapping = (
            pd.read_parquet(path)
            .rename(columns={'S_INFO_WINDCODE': 'PRODUCT', 'FS_MAPPING_WINDCODE': 'CONTRACT'})
        )
        mapping = mapping.dropna(subset=['PRODUCT', 'CONTRACT'])
        mapping['CONTRACT_PATCHED'] = mapping.apply(_patch_czc_contract_decade, axis=1)
        mapping['CONTRACT_UID'] = mapping['CONTRACT_PATCHED'].apply(_contract_to_uid)
        mapping = mapping.dropna(subset=['CONTRACT_UID'])
        mapping = mapping[['PRODUCT', 'CONTRACT_UID']].drop_duplicates()

        contract_to_product = {
            str(row.CONTRACT_UID): str(row.PRODUCT)
            for row in mapping.itertuples(index=False)
        }
        product_to_contracts: Dict[str, List[str]] = {}
        for contract_uid, product_name in contract_to_product.items():
            product_to_contracts.setdefault(product_name, []).append(contract_uid)

        _CNFUTURES_CONTRACT_TO_PRODUCT_BY_PATH[path] = contract_to_product
        _CNFUTURES_PRODUCT_TO_CONTRACTS_BY_PATH[path] = product_to_contracts
    return (
        _CNFUTURES_CONTRACT_TO_PRODUCT_BY_PATH[path],
        _CNFUTURES_PRODUCT_TO_CONTRACTS_BY_PATH[path],
    )

class CNFuturesContract(FuturesContract):
    """中国期货单个合约（固定计价货币 CNY，时区 Asia/Shanghai）。"""
    def __init__(self, name: str, point_value: Optional[int] = None):
        super().__init__(name, point_value, 'CNY', timezone='Asia/Shanghai')

    def get_parent_product(self, term_structure_paths: Optional[list[str]] = None):
        if getattr(self, '_parent_product_loaded', False):
            return getattr(self, '_parent_product_cache', None)
        parent = CNFutures.get_contract_parent(self.name)
        setattr(self, '_parent_product_cache', parent)
        setattr(self, '_parent_product_loaded', True)
        return parent

class CNFutures(Futures):
    """中国期货主力品种，附带行业分类、细分行业分类、日夜盘时段分类及中文品种名称。"""

    def __init__(self, name: str, point_value: Optional[int] = None, 
                 roller_info_path: Optional[str] = None,
                 data_path: Optional[str] = None,
                 term_structure_path: Optional[str] = None):
        super().__init__(
            name,
            point_value,
            'CNY',
            roller_info_path,
            term_structure_path,
            CNFuturesContract,
            timezone='Asia/Shanghai',
        )
        self.alias = name.split('@')[0]
        self.code = self.alias.split('.')[0]
        exchange_short = self.alias.split('.')[1] if '.' in self.alias else None
        self.version = name.split('@')[1] if '@' in name else _infer_unique_version(self.code, exchange_short)
        self.desc = get_by_code_and_version(self.code, self.version, variety_col_name) or self.alias
        _CNFUTURES_BY_NAME[self.name] = self
        _CNFUTURES_BY_NAME[self.alias] = self

    @classmethod
    def get_by_product_name(cls, product_name: str) -> Optional["CNFutures"]:
        return _CNFUTURES_BY_NAME.get(str(product_name))

    # ------------------------------------------------------------------
    # 品种中文名 → 品种代码 反向映射
    # ------------------------------------------------------------------
    _DESC_TO_CODE: Dict[str, str] | None = None  # lazy loaded

    @classmethod
    def desc_to_code(cls, desc: str, extra_map: Dict[str, str] | None = None) -> str:
        """根据合约标的（中文名）返回品种代码。

        数据源：sectors.csv 的「合约标的」→「品种代码」。
        首次调用会构建缓存映射。
        可传入 extra_map 补充 sectors.csv 覆盖不到的别名（如国信页面用名）。
        未找到时返回原字符串。
        """
        if cls._DESC_TO_CODE is None:
            cls._DESC_TO_CODE = {}
            for _, row in _data.iterrows():
                variety = str(row[variety_col_name]).strip()
                code = str(row[code_col_name]).strip()
                if variety and code:
                    cls._DESC_TO_CODE[variety] = code
        desc_str = str(desc)
        # priority: extra_map > sectors.csv
        if extra_map and desc_str in extra_map:
            return extra_map[desc_str]
        return cls._DESC_TO_CODE.get(desc_str, desc)

    # ------------------------------------------------------------------
    # 交易所 → 品种中文名列表（用于反向排除等场景）
    # ------------------------------------------------------------------
    _PRODUCTS_BY_EXCHANGE: Dict[str, List[str]] | None = None

    @classmethod
    def products_by_exchange(cls) -> Dict[str, List[str]]:
        """返回 {交易所代码: [合约标的...]} 的映射。"""
        if cls._PRODUCTS_BY_EXCHANGE is None:
            result: Dict[str, List[str]] = {}
            for _, row in _data.iterrows():
                exch_raw = str(row.get(exchange_code_col_name, "")).strip()
                variety = str(row.get(variety_col_name, "")).strip()
                if not exch_raw or not variety:
                    continue
                exch_map = {
                    "SHF": "SHFE", "CZC": "CZCE", "CFE": "CFFEX",
                    "GFE": "GFEX", "DCE": "DCE", "INE": "INE",
                }
                exch_code = exch_map.get(exch_raw, exch_raw)
                result.setdefault(exch_code, [])
                if variety not in result[exch_code]:
                    result[exch_code].append(variety)
            cls._PRODUCTS_BY_EXCHANGE = result
        return cls._PRODUCTS_BY_EXCHANGE

    @classmethod
    def get_contract_parent(cls, contract_uid: str, mapping_path: Optional[str] = None) -> Optional["CNFutures"]:
        contract_to_product, _ = _cn_futures_contract_maps(mapping_path)
        product_name = contract_to_product.get(str(contract_uid))
        return cls.get_by_product_name(product_name) if product_name else None

    @classmethod
    def get_contracts_for_product(cls, product_name: str, mapping_path: Optional[str] = None) -> List[str]:
        _, product_to_contracts = _cn_futures_contract_maps(mapping_path)
        return list(product_to_contracts.get(str(product_name), []))

    def get_roller_info_path(self) -> str:
        if not hasattr(self, '_ROLLER_INFO_PATH_CACHED'):
            from scripts.data_dir import DATA_DIR
            self._ROLLER_INFO_PATH_CACHED = os.path.join(DATA_DIR, 'roller_info.parquet')
        return self._ROLLER_INFO_PATH_CACHED

    def get_term_structure_path(self) -> str:
        if self.term_structure_path:
            return self.term_structure_path
        if not hasattr(self, '_TERM_STRUCTURE_PATH_CACHED'):
            from sources.LocalCNFutures import TERM_STRUCTURE_PATH
            self._TERM_STRUCTURE_PATH_CACHED = TERM_STRUCTURE_PATH
        return self._TERM_STRUCTURE_PATH_CACHED

from tools.products.Product import Product

def get_all_futures_contract() -> List[Product]:
    """返回合约粒度的所有 CNFuturesContract 列表（基于合约分钟数据目录）。"""

    data_dir_min = os.path.join(DATA_DIR, 'data_mink_product')

    from tools import DataFreq
    from tools.data.DataProviderProductTS import DataProviderProductTS
    futures_contract_ds_min1 = DataProviderProductTS(
        alias = 'LocalCNFuturesContractMIN1',
        data_freq = DataFreq.MIN1,
        if_object_is_in_source=lambda object: 
            os.path.isfile(os.path.join(data_dir_min, f"{object.alias}.{data_type}")),
        get_object_path=lambda object: os.path.join(data_dir_min, f"{object.alias}.{data_type}"),
        timezone = 'Asia/Shanghai',
        time_cols_mapping={'trade_time': '1min', 'trading_day': '1day'},
        data_cols_mapping=datacolumn_map_reversed,
    )

    contract_list = []
    for file_path in os.listdir(data_dir_min):
        if file_path.endswith('.' + data_type):
            code = file_path.split('.')[0]
            contract = CNFuturesContract(name=code)
            contract_list.append(contract)
    return contract_list

def get_object_path(object: Product, folder: str):
    path = os.path.join(folder, f"{object.alias}.{data_type}")
    
    if not isinstance(object, CNFutures) or not os.path.isfile(path):
        return ''
    else:
        import pyarrow.parquet as pq
        parquet_file = pq.ParquetFile(path)
        target_col = 'trade_time'

        # 1. 获取所有列名，找到目标列的索引
        schema = parquet_file.schema_arrow
        col_names = schema.names
        if target_col not in col_names:
            return path
        col_idx = col_names.index(target_col)

        # 2. 遍历所有 Row Group，取出该列统计信息中的最小值
        min_value = None
        for i in range(parquet_file.num_row_groups):
            rg_meta = parquet_file.metadata.row_group(i)
            col_meta = rg_meta.column(col_idx)
            stats = col_meta.statistics
            
            if stats is not None and stats.min is not None:
                current_min = stats.min
                if min_value is None or current_min < min_value:
                    min_value = current_min

        if min_value is None:
            # 如果统计信息缺失，退化为读取整列数据（较慢）
            table = pq.read_table(path, columns=[target_col])
            min_value = table[target_col].min().as_py()

        enddate = get_by_code_and_version(object.code, object.version, enddate_col_name)
        if enddate is not None and pd.Timestamp(min_value) > pd.Timestamp(enddate):
            return ''
        return path

def get_all_futures() -> List[CNFutures]:
    """注册 MIN1/DAY1 数据源并返回全量 CNFutures 主力品种列表。"""

    from tools import DataFreq
    from tools.data.DataProviderProductTS import DataProviderProductTS
    futures_ds_min1 = DataProviderProductTS(
        alias = 'LocalCNFuturesMIN1',
        data_freq = DataFreq.MIN1,
        get_object_path=lambda object: get_object_path(object, data_dir_min),
        timezone = 'Asia/Shanghai',
        time_cols_mapping={'trade_time': '1min', 'trading_day': '1day'},
        data_cols_mapping=datacolumn_map_reversed,
    )
    futures_ds_day1 = DataProviderProductTS(
        alias = 'LocalCNFuturesDAY1',
        data_freq = DataFreq.DAY1,
        get_object_path=lambda object: get_object_path(object, data_dir_day),
        timezone = 'Asia/Shanghai',
        time_cols_mapping={'trading_day': '1day'},
        data_cols_mapping=datacolumn_map_reversed,
    )

    # 先统计同一 code+exchange 下版本数，单版本则省略 @version。
    _tmp = _data.copy()
    _tmp['_KEY'] = _tmp[code_col_name].astype(str) + '|' + _tmp[exchange_code_col_name].astype(str)
    version_count = _tmp.groupby('_KEY')[version_col_name].nunique(dropna=True).to_dict()

    cnfutures_list = []
    for _, row in _data.iterrows():
        code = str(row[code_col_name])
        exchange_raw = str(row[exchange_code_col_name])
        exchange = exchange_map.get(exchange_raw, exchange_raw)
        version = str(row[version_col_name])
        key = f"{code}|{exchange_raw}"
        if version_count.get(key, 0) <= 1:
            name = f"{code}.{exchange}"
        else:
            name = f"{code}.{exchange}@{version}"
        cnfutures_list.append(CNFutures(name))

    return cnfutures_list

CNFUTURES = get_all_futures()
CNFUTURES_CATEGORY_SECTOR = {}
CNFUTURES_CATEGORY_DAYNIGHT = {}
for product in CNFUTURES:
    CNFUTURES_CATEGORY_SECTOR[product] = get_by_code_and_version(product.code, product.version, category_col_name)
    day_time = get_by_code_and_version(product.code, product.version, day_time_col_name)
    night_time = get_by_code_and_version(product.code, product.version, night_time_col_name)
    CNFUTURES_CATEGORY_DAYNIGHT[product] = f"{day_time},{night_time}"

from tools.products.categories.Category import Category

CNFuturesSectorCategory = Category(
    alias = '行业',
    type = CNFutures,
    categories = list(set(CNFUTURES_CATEGORY_SECTOR.values())),
)
CNFuturesSectorCategory._whether_is_in_category = lambda catname, obj: catname == CNFUTURES_CATEGORY_SECTOR.get(obj)
CNFuturesSectorCategory.objs = CNFUTURES

CNFuturesDayNightTimeCategory = Category(
    alias = '日夜盘',
    type = CNFutures,
    categories = list(set(CNFUTURES_CATEGORY_DAYNIGHT.values())),
)
CNFuturesDayNightTimeCategory._whether_is_in_category = lambda catname, obj: catname == CNFUTURES_CATEGORY_DAYNIGHT.get(obj)
CNFuturesDayNightTimeCategory.objs = CNFUTURES

def get_value_alias_for_day_night_time_category(x: str) -> str:
    """將日夜盘时段描述字符串转换为简短别名（如 '夜盘2'），用于分类显示。"""
    if '15:15' in x:
        return '日盘2'
    if '09:30' in x:
        return '日盘3'
    if '23:00' in x:
        return '夜盘1'
    if '01:00' in x:
        return '夜盘2'
    if '02:30' in x:
        return '夜盘3'
    if '21:00' not in x:
        return '日盘'
    return x
CNFuturesDayNightTimeCategory.get_value_alias = get_value_alias_for_day_night_time_category

CNFuturesSectorNightTimeCategory = CNFuturesSectorCategory * CNFuturesDayNightTimeCategory
