from typing import Any, List, Optional, Tuple
import pandas as pd
import os
from tools.products.Futures import Futures, FuturesContract
from tools import DataColumn

_data = pd.read_csv('../data/sectors.csv')
data_dir_min = '../data/main_mink'
data_path_day = '../data/main_series_adjusted.parquet'
data_dir_day = '../data/main_dayk'
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


def _infer_unique_version(code: str, exchange_short: Optional[str] = None) -> Optional[str]:
    """Infer version when a product has exactly one version in metadata."""
    df = _data[_data[code_col_name].astype(str) == str(code)]
    if exchange_short is not None:
        exch = exchange_map_reversed.get(exchange_short, exchange_short)
        df = df[df[exchange_code_col_name].astype(str) == str(exch)]
    versions = sorted(set(df[version_col_name].dropna().astype(str)))
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

class CNFuturesContract(FuturesContract):
    """中国期货单个合约（固定计价货币 CNY，时区 Asia/Shanghai）。"""
    def __init__(self, name: str, point_value: Optional[int] = None):
        super().__init__(name, point_value, 'CNY', timezone='Asia/Shanghai')

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

    def get_roller_info_path(self) -> str:
        if not hasattr(self, '_ROLLER_INFO_PATH_CACHED'):
            from Settings import DATA_DIR
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

    data_dir_min = '../data/data_mink_product'

    from tools import DataSource, DataFreq
    futures_contract_ds_min1 = DataSource(
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

    from tools import DataSource, DataFreq
    futures_ds_min1 = DataSource(
        alias = 'LocalCNFuturesMIN1',
        data_freq = DataFreq.MIN1,
        get_object_path=lambda object: get_object_path(object, data_dir_min),
        timezone = 'Asia/Shanghai',
        time_cols_mapping={'trade_time': '1min', 'trading_day': '1day'},
        data_cols_mapping=datacolumn_map_reversed,
    )
    futures_ds_day1 = DataSource(
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
        code = row[code_col_name]
        exchange = row[exchange_code_col_name]
        exchange = exchange_map.get(exchange, exchange)
        version = str(row[version_col_name])
        key = f"{code}|{row[exchange_code_col_name]}"
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
