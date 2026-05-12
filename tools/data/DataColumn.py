# =============================================================================
# tools/data/DataColumn.py
# 数据列枚举模块
#
# 定义全项目支持的数据列。使用自定义元类 (DataColumnMeta) 支持多种写法直接访问枚举成员：
#   DataColumn('OPEN') / DataColumn('O') / DataColumn('DataColumn.OPEN') / DataColumn['OPEN']
# =============================================================================
from enum import EnumMeta, Enum
from typing import Any

import sys; from pathlib import Path; sys.path.insert(0, str(Path(__file__).parent.parent.parent))

class DataColumnMeta(EnumMeta):
    """
    DataColumn 的元类。

    扩展了标准 EnumMeta，使得可配了三种方式构造枚举成员：
      1. 通过存储的简短代号，如 'O'
      2. 通过枚举成员名，如 'OPEN'
      3. 通过带前缀的名称，如 'DataColumn.OPEN'
    同样支持 cls['OPEN'] 下标语法。
    """
    def __call__(cls, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        """DataColumn('OPEN') / DataColumn('O') / DataColumn('DataColumn.OPEN') 均可正确解析。"""
        if not args:
            return super().__call__(*args, **kwargs)
        value = args[0]
        # 如果已经是枚举实例，直接返回
        if isinstance(value, cls):
            return value
        try:
            # 尝试通过存储值（如 'O'）或去掉前缀后的名称（如 'OPEN'）
            return super().__call__(value.removeprefix('DataColumn.'))
        except ValueError:
            pass
        try:
            # 尝试通过键名访问（查找枚举成员名）
            return super().__getitem__(value.removeprefix('DataColumn.'))
        except KeyError:
            raise ValueError(f"Invalid data column: {value}")
        
    def __getitem__(cls, key):
        """DataColumn['OPEN'] 下标语法支持。"""
        return cls.__call__(key)
        
class DataColumn(Enum, metaclass=DataColumnMeta):
    """
    数据列枚举。

    每个成员对应一个数据列类型，存储值为简短字符串代号，
    实际数据文件中的列名则由 DataSource.data_cols_mapping 提供映射。
    """    
    OPEN = 'O'                  # 开盘价
    HIGH = 'H'                  # 最高价
    LOW = 'L'                   # 最低价
    CLOSE = 'C'                 # 收盘价
    VOLUME = 'V'                # 成交量
    TURNOVER = 'TO'             # 成交额
    OPEN_INTEREST = 'OI'        # 持仓量
    TIME_COL_DAY = 'TD'         # 日期时间列（资产管理日）
    TIME_COL_MIN = 'TM'         # 分钟级时间列
    TIMESTAMP = 'T'             # 精确时间戳
    TWAP = 'TW'                 # 时间加权均价
    VWAP = 'VW'                 # 成交量加权均价
    SETTLEMENT_PRICE = 'SP'     # 结算价
    ADJUSTMENT_MUL = 'AM'       # 复权乘数
    ADJUSTMENT_ADD = 'AA'       # 复权加数
    UPPER_LIMIT_PRICE = 'ULP'   # 涨停价
    LOWER_LIMIT_PRICE = 'LLP'   # 跌停价
    PRE_SETTLEMENT_PRICE = 'PSP'# 前一交易日结算价
    OPEN_ADJUSTED = 'OA'        # 复权开盘价
    HIGH_ADJUSTED = 'HA'        # 复权最高价
    LOW_ADJUSTED = 'LA'         # 复权最低价
    CLOSE_ADJUSTED = 'CA'       # 复权收盘价
    ADJUST_SUFFIX = 'ADJ'       # 复权后缀标记
    PRODUCT_NAME = 'PN'         # 品种名称（用于多品种合并表中过滤）

if __name__ == '__main__':
    DataColumn('OPEN')
    DataColumn('O')
    DataColumn('DataColumn.OPEN')
    DataColumn['OPEN']
    DataColumn['O']
    DataColumn['DataColumn.OPEN']