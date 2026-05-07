# =============================================================================
# Factors/OiAmtChgRat.py
# 持仓金额变化率因子
#
# FactorFamily 表达式驱动版本。
# oi_amt = P * OI; X = oi_amt.delta(N) / oi_amt.shift(N)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class OiAmtChgRat(FactorFamily):
    """持仓金额变化率。\n\n    参数：\n        P (DataColumn) : 价格列\n        OI (DataColumn) : 持仓量列\n        N (Timedelta)   : 回看窗口"""


    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        OI = DataColumnParam('OI', default_value='OI')
        N = WindowParam('N', default_value='10d')
        p = P.shift(0)
        oi = OI.shift(0)
        oi_amt = p * oi
        return oi_amt.delta(N) / (oi_amt.shift(N) + 1e-10)

    desc = '持仓金额变化率'
    description = """
## 这是什么
OiAmtChgRat 用价格乘以持仓量得到持仓金额，然后计算 N 期变化率。

## 它在看什么
不仅看资金入场量，还考虑入场价位。金额扩张代表真金白银的流入。

## 为什么这个因子可能行得通
金额比纯持仓量更全面。高位加仓时金额增速会被放大，因子对"重仓追高"更敏感。

## 使用提醒
价格快速上涨时因子天然偏高——这是特征而非缺陷，反映的是资金追逐的强度。

## 反转信号
持仓金额增速骤降常领先于价格转向，是聪明钱离场的先兆。
"""

if __name__ == '__main__':
    ff = OiAmtChgRat()
    ff.add_params(F='1d')
