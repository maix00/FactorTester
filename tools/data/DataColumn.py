from enum import EnumMeta, Enum
from typing import Any

import sys; from pathlib import Path; sys.path.insert(0, str(Path(__file__).parent.parent.parent))

class DataColumnMeta(EnumMeta):
    def __call__(cls, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        if not args:
            return super().__call__(*args, **kwargs)
        value = args[0]
        if isinstance(value, cls):
            return value
        try:
            return super().__call__(value.removeprefix('DataColumn.'))
        except ValueError:
            pass
        try:
            return super().__getitem__(value.removeprefix('DataColumn.'))
        except KeyError:
            raise ValueError(f"Invalid data column: {value}")
        
    def __getitem__(cls, key):
        return cls.__call__(key)
        
class DataColumn(Enum, metaclass=DataColumnMeta):
    OPEN = 'O'
    HIGH = 'H'
    LOW = 'L'
    CLOSE = 'C'
    VOLUME = 'V'
    TURNOVER = 'TO'
    OPEN_INTEREST = 'OI'
    TIME_COL_DAY = 'TD'
    TIME_COL_MIN = 'TM'
    TIMESTAMP = 'T'
    TWAP = 'TW'
    VWAP = 'VW'
    SETTLEMENT_PRICE = 'SP'
    ADJUSTMENT_MUL = 'AM'
    ADJUSTMENT_ADD = 'AA'
    UPPER_LIMIT_PRICE = 'ULP'
    LOWER_LIMIT_PRICE = 'LLP'
    PRE_SETTLEMENT_PRICE = 'PSP'
    OPEN_ADJUSTED = 'OA'
    HIGH_ADJUSTED = 'HA'
    LOW_ADJUSTED = 'LA'
    CLOSE_ADJUSTED = 'CA'
    ADJUST_SUFFIX = 'ADJ'
    PRODUCT_NAME = 'PN'

if __name__ == '__main__':
    DataColumn('OPEN')
    DataColumn('O')
    DataColumn('DataColumn.OPEN')
    DataColumn['OPEN']
    DataColumn['O']
    DataColumn['DataColumn.OPEN']