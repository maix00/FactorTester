from typing import Any, List, Optional, Tuple
import pandas as pd
import os
from Products import Futures, FuturesContract
from Tools import DataColumn

_data = pd.read_csv('../data/sectors.csv')
data_dir_min = '../data/main_mink/'
data_dir_day = '../data/main_dayk/'
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
    DataColumn.TIME_COL: 'trade_time',
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
night_time = '夜盘时间'
day_time = '日盘时间'

def get_variety_by_code(code) -> str | None:
    """从代码返回品种"""
    result = _data[_data[code_col_name] == code][variety_col_name]
    return result.values[0] if len(result) > 0 else None

def get_exchange_code_by_code(code) -> str | None:
    """从代码返回交易所代码"""
    result = _data[_data[code_col_name] == code][exchange_code_col_name]
    return result.values[0] if len(result) > 0 else None

def get_category_by_code(code, flag: int = 2) -> str | None:
    """从代码返回类别"""
    categories_with_codes = get_categories_with_codes(flag=flag)
    for category, codes in categories_with_codes.items():
        if code in codes:
            return category
    return None

def get_day_night_time_category_by_code(code) -> Tuple[str, str]:
    _series = _data[day_time] + ', ' + _data[night_time].fillna('None')
    _data['day_night_time'] = _series
    categories_list = list(_series.unique())
    for i in range(len(categories_list)):
        if _data[_data[code_col_name] == code]['day_night_time'].values[0] == categories_list[i]:
            return f"{i}", categories_list[i]
    return '', ''

def get_all_day_night_time_categories() -> list[str]:
    _series = _data[day_time] + ', ' + _data[night_time].fillna('None')
    return _series.dropna().unique().tolist()

def get_codes_by_exchange_code(exchange_code) -> list[str]:
    """从交易所代码返回所有的代码"""
    return _data[_data[exchange_code_col_name] == exchange_code][code_col_name].tolist()

def get_exchange_by_exchange_code(exchange_code) -> str | None:
    """从交易所代码返回对应的交易所"""
    result = _data[_data[exchange_code_col_name] == exchange_code][exchange_col_name]
    return result.values[0] if len(result) > 0 else None

def get_codes_by_category(category) -> list[str]:
    """从类别返回所有的代码"""
    return _data[_data[category_col_name] == category][code_col_name].tolist()

def get_all_categories() -> list[str]:
    """返回所有的类别"""
    return _data[category_col_name].unique().tolist()

def get_categories_with_codes(flag: int = 2) -> dict[str, list[str]]:
    """返回所有类别及其对应的代码的dict，根据夜盘时间进一步分组"""
    if flag == 1:
        return _data.groupby(category_col_name)[code_col_name].apply(list).to_dict()  # type: ignore
    elif flag == 2:
        return get_categories_2_with_codes()
    else:
        raise ValueError("Invalid flag value. Use 1 for basic categories or 2 for categories further grouped by night trading time.")

def get_categories_2_with_codes() -> dict[str, list[str]]:
    result = {}
    grouped = _data.groupby(category_col_name)
    for category, group in grouped:
        series = group[night_time].copy().fillna('0')
        night_times = series.unique()
        if len(night_times) == 1:
            result[category] = group[code_col_name].tolist()
        else:
            for i, night_t in enumerate(night_times, 1):
                key = f"{category}{i}"
                result[key] = group[series == night_t][code_col_name].tolist()
    return result

def check_data_files():
    """检查数据文件是否与代码表中的品种匹配"""
    for string in ['min', 'day']:
        file_list = file_list_min if string == 'min' else file_list_day
        codes_in_data = set()
        for file_path in file_list:
            code = file_path.split('/')[-1].split('.')[0]
            codes_in_data.add(code)
        codes_in_table = set(_data[code_col_name].tolist())
        missing_in_data = codes_in_table - codes_in_data
        extra_in_data = codes_in_data - codes_in_table
        if missing_in_data:
            print(f'Codes in table but missing in data files ({string}):', missing_in_data)
        if extra_in_data:
            print(f'Codes in data files ({string}) but not in table:', extra_in_data)

def get_categories_with_products(flag: int = 2) -> dict[str, list[CNFutures]]:
    """返回所有类别及其对应的品种的dict"""
    categories_with_products = {}
    categories_with_codes = get_categories_with_codes(flag=flag)
    for category, codes in categories_with_codes.items():
        products = []
        for code in codes:
            exchange = get_exchange_code_by_code(code)
            if exchange is not None:
                mapped_exchange = exchange_map.get(exchange, exchange)
                products.append(CNFutures(name = code + '.' + mapped_exchange))
        categories_with_products[category] = products
    return categories_with_products

class CNFuturesContract(FuturesContract):
    def __init__(self, name: str, point_value: Optional[int] = None):
        super().__init__(name, point_value, 'CNY')

class CNFutures(Futures):
    def __init__(self, name: str, point_value: Optional[int] = None, 
                 mappings_path: Optional[str] = None, 
                 data_path: Optional[str] = None):
        super().__init__(name, point_value, 'CNY', mappings_path, data_path, CNFuturesContract)
        self.category_sector_cn = get_category_by_code(name.split('.')[0], flag = 1) if name else None
        self.category_sector_cn_night_time = get_category_by_code(name.split('.')[0], flag = 2) if name else None
        self.category_day_night_time, self.category_day_night_time_desc = \
            get_day_night_time_category_by_code(name.split('.')[0]) if name else ('', '')
        self.category_attr_name = 'category_day_night_time'

from Products import Product

def get_all_futures_contract() -> List[Product]:

    data_dir_min = '../data/data_mink_product/'

    from Tools import DataSource, DataFreq
    LocalCNFuturesContractMIN1 = DataSource(
        alias = 'LocalCNFuturesContractMIN1',
        data_freq = DataFreq.MIN1,
        if_object_is_in_source=lambda object: 
            os.path.isfile(os.path.join(data_dir_min, object.alias + '.' + data_type)),
        get_object_path=lambda object: os.path.join(data_dir_min, object.alias + '.' + data_type)
    )
    LocalCNFuturesContractMIN1.set_data_cols_mapping(datacolumn_map_reversed)
    LocalCNFuturesContractMIN1.set_time_cols_mapping({'trade_time': '1min', 'trading_day': '1day'})
    from Tools import DataSourceRegister
    DataSourceRegister().register(LocalCNFuturesContractMIN1)

    contract_list = []
    for file_path in os.listdir(data_dir_min):
        if file_path.endswith('.' + data_type):
            code = file_path.split('.')[0]
            contract = CNFuturesContract(name=code)
            contract_list.append(contract)
    return contract_list

def get_all_futures() -> List[Product]:

    from Tools import DataSource, DataFreq
    LocalCNFuturesMIN1 = DataSource(
        alias = 'LocalCNFuturesMIN1',
        data_freq = DataFreq.MIN1,
        if_object_is_in_source=lambda object: 
            os.path.isfile(os.path.join(data_dir_min, object.alias + '.' + data_type)),
        get_object_path=lambda object: os.path.join(data_dir_min, object.alias + '.' + data_type)
    )
    LocalCNFuturesDAY1 = DataSource(
        alias = 'LocalCNFuturesDAY1',
        data_freq = DataFreq.DAY1,
        if_object_is_in_source=lambda object: 
            os.path.isfile(os.path.join(data_dir_day, object.alias + '.' + data_type)),
        get_object_path=lambda object: os.path.join(data_dir_day, object.alias + '.' + data_type)
    )

    LocalCNFuturesMIN1.set_data_cols_mapping(datacolumn_map_reversed)
    LocalCNFuturesDAY1.set_data_cols_mapping(datacolumn_map_reversed)

    LocalCNFuturesMIN1.set_time_cols_mapping({'trade_time': '1min', 'trading_day': '1day'})
    LocalCNFuturesDAY1.set_time_cols_mapping({'trading_day': '1day'})

    from Tools import DataSourceRegister
    DataSourceRegister().register(LocalCNFuturesMIN1)
    DataSourceRegister().register(LocalCNFuturesDAY1)

    categories_with_products = get_categories_with_products()
    cnfutures_list = []
    for products in categories_with_products.values():
        cnfutures_list.extend(products)

    return cnfutures_list

if __name__ == '__main__':
    # check_data_files()
    # categories_with_products = get_categories_with_products()
    # for category, products in categories_with_products.items():
    #     print(f"Category: {category}")
    #     print(f"  Products: {products}")

    all_cn_futures = get_all_futures()
    # print(all_cn_futures[0].get_some_data())

    product = all_cn_futures[0]
    get_day_night_time_category_by_code(product.name.split('.')[0])

def get_futures_cateogory_map():
    return {
        'category_sector_cn_night_time': 'category_sector_cn',
        'category_sector_cn': '__class__.__name__',
        'category_day_night_time': '__class__.__name__'
    }

def get_futures_contract_category_map():
    return {}

from Category import Category

CNFuturesSectorCategory = Category(
    alias = '行业',
    type = CNFutures,
    categories = get_all_categories(),
)
CNFuturesSectorCategory._whether_is_in_category = lambda catname, obj: get_category_by_code(obj.name.split('.')[0], flag = 1) == catname
CNFuturesSectorCategory.objs = get_all_futures()

CNFuturesDayNightTimeCategory = Category(
    alias = '日夜盘',
    type = CNFutures,
    categories = get_all_day_night_time_categories(),
)
CNFuturesDayNightTimeCategory._whether_is_in_category = lambda catname, obj: get_day_night_time_category_by_code(obj.name.split('.')[0])[1] == catname
CNFuturesDayNightTimeCategory.objs = get_all_futures()

def get_value_alias_for_day_night_time_category(x: str) -> str:
    if '15:15' in x:
        return '日盘2'
    if '21:00' not in x:
        return '日盘'
    if '23:00' in x:
        return '夜盘1'
    if '01:00' in x:
        return '夜盘2'
    if '02:30' in x:
        return '夜盘3'
    return x
CNFuturesDayNightTimeCategory.get_value_alias = get_value_alias_for_day_night_time_category

CNFuturesSectorNightTimeCategory = CNFuturesSectorCategory * CNFuturesDayNightTimeCategory

if __name__ == '__main__':
    print(CNFuturesSectorCategory.categories)
    print(CNFuturesDayNightTimeCategory.categories)

    # print(CNFuturesSectorNightTimeCategory.categories)
    # for catname in CNFuturesSectorNightTimeCategory.categories:
    #     print(f"Category: {catname}, Value Alias: {CNFuturesSectorNightTimeCategory.get_value_alias(catname)}")
    
    tree1 = CNFuturesSectorCategory.get_tree()
    tree2 = CNFuturesDayNightTimeCategory.get_tree(ancester=Product)
    # print(tree1, tree2)
    
    # from Category import combine_trees
    # print(combine_trees(tree1, tree2).tree)

    print(CNFuturesSectorNightTimeCategory.get_tree().tree)
    print(CNFuturesSectorNightTimeCategory.get_tree_with_parents_without_products(ancester=Product).tree)
