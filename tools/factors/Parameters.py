# =============================================================================
# tools/factors/Parameters.py
# 因子系统专用参数模块
#
# 定义因子计算中共用的参数单例：
#   FactorFreqParam       - 因子信号频率，F，出现在因子别名中
#   FactorNextPeriodReturns - 下期收益类型枚举（OPEN到OPEN、CLOSE到CLOSE 等）
# =============================================================================

from enum import Enum
from typing import Optional, Any

from tools.decorators import factor_workspace
from tools.data.types import DataColumn
from tools.parameters import Parameter, ValueSpace


def _to_rev_bool(value: Any) -> bool:
    """将多种输入规范化为是否反转：True/1/-1 表示反转，False/0 表示不反转。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value in (1, -1):
            return True
        if value == 0:
            return False
        raise ValueError(f"Invalid reverse flag: {value}")
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ('1', '-1', 'true', 't', 'yes', 'y', 'rev', 'reverse'):
            return True
        if v in ('0', 'false', 'f', 'no', 'n', 'normal', 'none'):
            return False
    raise ValueError(f"Invalid reverse flag: {value}")

class ReverseSignalParam(Parameter):
    """Whether a factor signal keeps or reverses its natural direction."""

    input_help = (
        "选择是否反转因子信号方向：0、False、no、normal 表示不反转；1、-1、True、yes、rev、"
        "reverse 表示反转。保存后规范化为 0 或 1。"
    )


class FactorFrequencyParam(Parameter):
    """Frequency at which a factor signal is emitted."""

    input_help = (
        "填写因子信号频率，支持任意正时间长度，例如 1m、5m、30m、1h、1d；特殊值 S 表示"
        "反转信号。该值会写入因子 alias。"
    )


def get_reverse_param(alias: Optional[str] = '$Rev', desc: Optional[str] = None) -> Parameter:
    """创建因子反转参数：1/True/-1 表示反转，0/False 表示不反转。"""
    space = ValueSpace(
        contains=_safe_is_rev,
        rectify=_to_rev_bool,
        alias=lambda x: '1' if _to_rev_bool(x) else '0',
    )
    param = ReverseSignalParam(
        alias=alias,
        value_space=space,
        default_value=False,
        desc=desc or '因子反转标志：1/True/-1 反转信号方向，0/False 保持信号方向不变',
    )
    return param

def _safe_is_rev(value: Any) -> bool:
    try:
        _to_rev_bool(value)
        return True
    except Exception:
        return False

def get_factor_freq_param(alias: Optional[str] = '$F', desc: Optional[str] = None) -> Parameter:
    """
    创建因子信号频率参数。
    默认值为 '30min'（日内频率），支持任意正 Timedelta 以及特殊枚举值 'S'（反转信号）。
    该参数的别名会出现在因子全名中。
    """
    td_space = ValueSpace.timedelta('pos')
    s_space = ValueSpace.finite(['S'])
    space = td_space.union(s_space)
    return FactorFrequencyParam(
        alias=alias,
        value_space=space,
        default_value='30min',
        desc=desc or '因子信号频率，支持任意正时长（如 30min、1d、5d）',
    )

# 全局单例参数对象
# 这些对象被共享给周期内的所有 Factor / FactorFamily / Product 实例公用
# 因子信号频率参数（如 '1d'、'5d'），不对应 IC 计算的收益频率
FactorFreqParam  = get_factor_freq_param(alias='$F')
# 因子反转参数：1/True/-1 表示反转；0/False 表示不反转
ReverseParam = get_reverse_param(alias='$Rev')

@factor_workspace
class FactorNextPeriodReturns(Enum):
    """
    因子下期收益类型枚举。

    每个成员封装一种收益计算方式的价格列：
      NEXT_OPEN_TO_OPEN           - 下期开盘→开盘收益（未进行复权）
      NEXT_OPEN_TO_OPEN_ADJUSTED  - 下期开盘→开盘复权收益（推荐）
      THIS_CLOSE_TO_CLOSE         - 本期收盘→收盘收益
      THIS_CLOSE_TO_CLOSE_ADJUSTED- 本期收盘→收盘复权收益
    """
    NEXT_OPEN_TO_OPEN = DataColumn.OPEN
    NEXT_OPEN_TO_OPEN_ADJUSTED = DataColumn.OPEN_ADJUSTED
    THIS_CLOSE_TO_CLOSE = DataColumn.CLOSE
    THIS_CLOSE_TO_CLOSE_ADJUSTED = DataColumn.CLOSE_ADJUSTED

__factor_workspace__ = (
    "FactorFreqParam",
    "ReverseParam",
)
