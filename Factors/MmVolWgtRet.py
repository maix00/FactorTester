# =============================================================================
# Factors/MmVolWgtRet.py
# 成交量加权收益因子
#
# FactorFamily 表达式驱动版本。
# X_t = sum(V_s * r_s) / sum(V_s) over N periods, r_s = (P_s - P_{s-RF})/P_{s-RF}
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmVolWgtRet(FactorFamily):
    """成交量加权收益因子。\n\n    参数：\n        P (DataColumn) : 价格列\n        N (Timedelta)  : 回看窗口\n        RF (Timedelta) : 收益步长"""


    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        N = WindowParam('N', default_value='10d')
        RF = WindowParam('RF', default_value='1d')
        V = DataColumnParam('V', default_value='V')
        r = P.delta(RF) / P.shift(RF)
        v = V.shift(0)
        return (v * r).rolling_sum(N) / (v.rolling_sum(N) + 1e-10)

    desc = '成交量加权收益'
    description = """
## 这是什么
MmVolWgtRet 是成交量加权收益因子，以成交量为权重的收益加权平均。

## 它在看什么
高成交量的收益贡献更大——试图回答方向是否有"量"的支持。

## 为什么这个因子可能行得通
量价配合是经典趋势确认手段。

## 使用提醒
极端放量后成交量萎缩会使权重分布失衡。

## 反转信号
量价背离——价格新高但 VWAP 下降——是典型的反转信号。
"""

if __name__ == '__main__':
    ff = MmVolWgtRet()
    ff.add_params(F='1d')
