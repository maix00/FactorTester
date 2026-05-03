# =============================================================================
# Factors/OiChgRatio.py
# 持仓量变化比值因子
#
# FactorFamily 表达式驱动版本。
# X = OI / OI.shift(N)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class OiChgRatio(FactorFamily):
    """持仓量变化比值。"""


    @staticmethod
    def factor_expr():
        N = WindowParam('N', default_value='5d')
        oi = DataColumnParam('OI', default_value='OI')
        oi_s = oi.shift(0)
        return oi_s / (oi_s.shift(N) + 1e-10)

    desc = '持仓量变化比值'
    description = """
## 这是什么
OiChgRatio 是当期持仓量与 N 期前持仓量的比值。

## 它在看什么
持续大于 1 意味着持仓在扩张，持续小于 1 意味着资金在抽离。

## 为什么这个因子可能行得通
比值天然标准化，对不同品种可比。比值持续高位代表资金深度介入。

## 使用提醒
该因子不区分方向，只反映资金参与度变化，需结合价格趋势使用。

## 反转信号
比值从高位急跌是资金撤退的明确证据，预示趋势终结。
"""

if __name__ == '__main__':
    ff = OiChgRatio()
    ff.add_params(F='1d')
