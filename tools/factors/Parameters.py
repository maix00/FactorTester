
from enum import Enum
from typing import Optional, Any

from tools import DataColumn
from tools.parameters.Parameter import Parameter, FinRangeParam, TimeDeltaParam, DateOrTimeParam

from Settings import default_test_start_date

def get_return_freq_param(alias: Optional[str] = '$RF') -> Parameter:
    param = FinRangeParam(alias, None, get_value_alias=lambda _: 'N')
    param += TimeDeltaParam(flag='pos', single_use=True)
    return param

def get_factor_freq_param(alias: Optional[str] = 'F') -> Parameter:
    param = TimeDeltaParam(alias=alias, default_value='1d', flag='pos')
    param += FinRangeParam(alias=None, value_space='S', single_use=True)
    return param

def get_StartCalcPointParam(alias: Optional[str] = '$SCP', default_value: Optional[Any] = None, **kwargs) -> DateOrTimeParam:
    return DateOrTimeParam(alias, default_value=default_value, **kwargs)

ReturnFreqParam = get_return_freq_param(alias='$RF')
FactorFreqParam = get_factor_freq_param(alias='F')
StartCalcPointParam = get_StartCalcPointParam(alias='$SCP', default_value=default_test_start_date, isDate=True)

class FactorNextPeriodReturns(Enum):
    NEXT_OPEN_TO_OPEN = DataColumn.OPEN
    NEXT_OPEN_TO_OPEN_ADJUSTED = DataColumn.OPEN_ADJUSTED
    THIS_CLOSE_TO_CLOSE = DataColumn.CLOSE
    THIS_CLOSE_TO_CLOSE_ADJUSTED = DataColumn.CLOSE_ADJUSTED