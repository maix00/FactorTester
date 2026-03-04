from typing import Any, List, Optional
import pandas as pd
import os
from Products import Futures, FuturesContract

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

exchange_map = {
    "DCE": "DCE",
    "CZCE": "CZC",
    "INE": "INE",
    "SHFE": "SHF",
    "CFFEX": "CFE",
    "GFEX": "GFE"
}

exchange_map_reversed = {v: k for k, v in exchange_map.items()}

code_col_name = '品种代码'
variety_col_name = '合约标的'
category_col_name = '类别'
exchange_col_name = '交易所'
exchange_code_col_name = '交易所代码'


def get_variety_by_code(code) -> str | None:
    """从代码返回品种"""
    result = _data[_data[code_col_name] == code][variety_col_name]
    return result.values[0] if len(result) > 0 else None

def get_exchange_code_by_code(code) -> str | None:
    """从代码返回交易所代码"""
    result = _data[_data[code_col_name] == code][exchange_code_col_name]
    return result.values[0] if len(result) > 0 else None

def get_category_by_code(code) -> str | None:
    """从代码返回类别"""
    result = _data[_data[code_col_name] == code][category_col_name]
    return result.values[0] if len(result) > 0 else None

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

def get_categories_with_codes() -> dict[str, list[str]]:
    """返回所有类别及其对应的代码的dict"""
    return _data.groupby(category_col_name)[code_col_name].apply(list).to_dict()

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

def get_categories_with_products() -> dict[str, list[CNFutures]]:
    """返回所有类别及其对应的品种的dict"""
    categories_with_products = {}
    categories_with_codes = get_categories_with_codes()
    for category, codes in categories_with_codes.items():
        products = []
        for code in codes:
            exchange = get_exchange_code_by_code(code)
            if exchange is not None:
                mapped_exchange = exchange_map.get(exchange, exchange)
                name = code + '.' + mapped_exchange
                product = CNFutures(name=name)

                data_path_min = os.path.join(data_dir_min, name + '.' + data_type)
                if data_path_min in file_list_min:
                    product.set_data_path(data_freq='1min', data_path=data_path_min)
                    product.set_time_cols_mapping('1min', {'1min': 'trade_time', '1day': 'trading_day'})
                
                data_path_day = os.path.join(data_dir_day, name + '.' + data_type)
                if data_path_day in file_list_day:
                    product.set_data_path(data_freq='1day', data_path=data_path_day)
                    product.set_time_cols_mapping('1day', {'1day': 'trading_day'})

                products.append(product)
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
        self.category_sector_cn = get_category_by_code(name.split('.')[0])
        self.category_attr_name = 'category_sector_cn'

def get_cnfutures() -> List[CNFutures]:
    categories_with_products = get_categories_with_products()
    cnfutures_list = []
    for products in categories_with_products.values():
        cnfutures_list.extend(products)
    return cnfutures_list

if __name__ == '__main__':
    check_data_files()
    categories_with_products = get_categories_with_products()
    for category, products in categories_with_products.items():
        print(f"Category: {category}")
        print(f"  Products: {products}")

    all_cn_futures = get_cnfutures()
    print(all_cn_futures[0].get_some_data())