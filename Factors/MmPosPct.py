# =============================================================================
# Factors/MmPosPct.py
# 正收益占比因子
#
# FactorFamily 表达式驱动版本。
# X_t = sum(1_{r_i>0}) / N over WF window (each step RF)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmPosPct(FactorFamily):
    """正收益占比（胜率）因子。\n\n    参数：\n        P (DataColumn) : 价格列\n        WF (Timedelta) : 统计窗口\n        RF (Timedelta) : 单期步长\n        F (Timedelta)  : 信号频率"""


    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        WF = WindowParam('WF', default_value='10m')
        RF = WindowParam('RF', default_value='1m')
        r = P.delta(RF) / P.shift(RF)
        return (r > 0).rolling_sum(WF) / WF

    desc = '正收益占比'
    description = """
## 这是什么
MmPosPct 是正收益占比（胜率）因子，统计过去 WF 窗口内正收益出现的比例。

## 它在看什么
只关心涨跌频率不关心幅度。

## 为什么这个因子可能行得通
高胜率环境里回调通常较浅。

## 使用提醒
纯频率统计忽略了幅度信息，建议与 MmUpRatio 配合。

## 反转信号
胜率维持在 0.7 以上过长时间，反转风险上升。
"""

if __name__ == '__main__':
    ff = MmPosPct()
    ff.add_params(F='1d')
