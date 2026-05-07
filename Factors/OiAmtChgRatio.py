# =============================================================================
# Factors/OiAmtChgRatio.py
# 持仓金额变化比值因子
#
# FactorFamily 表达式驱动版本。
# oi_amt = P * OI; X = oi_amt / oi_amt.shift(N)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class OiAmtChgRatio(FactorFamily):
    """持仓金额变化比值。\n\n    参数：\n        P (DataColumn) : 价格列\n        OI (DataColumn) : 持仓量列\n        N (Timedelta)   : 回看窗口"""


    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        OI = DataColumnParam('OI', default_value='OI')
        N = WindowParam('N', default_value='10d')
        p = P.shift(0)
        oi = OI.shift(0)
        oi_amt = p * oi
        return oi_amt / (oi_amt.shift(N) + 1e-10)

    desc = '持仓金额变化比值'
    description = """
## 这是什么
OiAmtChgRatio 是当期持仓金额与 N 期前持仓金额的比值。

## 它在看什么
比值 > 1 意味资金在堆叠，比值 < 1 意味资金在撤离。对涨跌中资金行为做全口径度量。

## 为什么这个因子可能行得通
该比值剔除了纯价格涨跌的影响（买卖两方都会影响金额），更纯粹地反映资金参与度变化。

## 使用提醒
与 OiChgRatio 相比，该因子还捕捉了持仓价格层面的信息，对极端行情的敏感度更高。

## 反转信号
比值从极端高位（>>1）回落是最可靠的资金退潮信号。
"""

if __name__ == '__main__':
    ff = OiAmtChgRatio()
    ff.add_params(F='1d')
