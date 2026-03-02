import pandas as pd
from Products import Futures

_data = pd.read_csv('../data/sectors.csv')

exchange_map = {
    "DCE": "DCE",
    "CZCE": "CZC",
    "INE": "INE",
    "SHFE": "SHF",
    "CFFEX": "CFE",
    "GFEX": "GFE"
}

def get_variety_by_code(code) -> str | None:
    """从代码返回品种"""
    result = _data[_data['代码'] == code]['品种']
    return result.values[0] if len(result) > 0 else None

def get_exchange_code_by_code(code) -> str | None:
    """从代码返回交易所代码"""
    result = _data[_data['代码'] == code]['交易所代码']
    return result.values[0] if len(result) > 0 else None

def get_category_by_code(code) -> str | None:
    """从代码返回类别"""
    result = _data[_data['代码'] == code]['类别']
    return result.values[0] if len(result) > 0 else None

def get_codes_by_exchange_code(exchange_code) -> list[str]:
    """从交易所代码返回所有的代码"""
    return _data[_data['交易所代码'] == exchange_code]['代码'].tolist()

def get_exchange_by_exchange_code(exchange_code) -> str | None:
    """从交易所代码返回对应的交易所"""
    result = _data[_data['交易所代码'] == exchange_code]['交易所']
    return result.values[0] if len(result) > 0 else None

def get_codes_by_category(category) -> list[str]:
    """从类别返回所有的代码"""
    return _data[_data['类别'] == category]['代码'].tolist()

def get_categories_with_codes() -> dict[str, list[str]]:
    """返回所有类别及其对应的代码的dict"""
    return _data.groupby('类别')['代码'].apply(list).to_dict()

def get_categories_with_products() -> dict[str, list[Futures]]:
    """返回所有类别及其对应的品种的dict"""
    categories_with_products = {}
    categories_with_codes = get_categories_with_codes()
    for category, codes in categories_with_codes.items():
        products = []
        for code in codes:
            exchange = get_exchange_code_by_code(code)
            if exchange is not None:
                mapped_exchange = exchange_map.get(exchange, exchange)
                products.append(Futures(code + '.' + mapped_exchange))
        categories_with_products[category] = products
    return categories_with_products

if __name__ == '__main__':
    categories_with_products = get_categories_with_products()
    for category, products in categories_with_products.items():
        print(f"Category: {category}")
        print(f"  Products: {products}")