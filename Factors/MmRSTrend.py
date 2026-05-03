# =============================================================================
# Factors/MmRSTrend.py
# Rogers-Satchell 波动趋势因子
#
# FactorFamily 表达式驱动版本。
# RS = ln(H/C)*ln(H/O) + ln(L/C)*ln(L/O); X = mean_N(sign(C-O) * RS)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmRSTrend(FactorFamily):
    """Rogers-Satchell 波动趋势因子。\n\n    参数：\n        N (Timedelta) : 天数"""


    @staticmethod
    def factor_expr():
        N = WindowParam('N', default_value='10d')
        O = DataColumnParam('O', default_value='OA')
        H = DataColumnParam('H', default_value='HA')
        L = DataColumnParam('L', default_value='LA')
        C = DataColumnParam('C', default_value='CA')
        hc = (H.shift(0) / C.shift(0)).log()
        ho = (H.shift(0) / O.shift(0)).log()
        lc = (L.shift(0) / C.shift(0)).log()
        lo = (L.shift(0) / O.shift(0)).log()
        rs = hc * ho + lc * lo
        return (rs * (C.shift(0) - O.shift(0)).sign()).ma(N)

    desc = 'RS 波动趋势'
    description = """
## 这是什么
MmRSTrend 是 Rogers-Satchell 波动趋势因子，结合波动大小和方向。

## 它在看什么
RS 对漂移项不敏感，适合有趋势的市场。

## 为什么这个因子可能行得通
区分"强趋势大波动"与"无方向大波动"。

## 使用提醒
RS 在非连续交易下可能有偏。

## 反转信号
RS 趋势在高位钝化后缩量。
"""

if __name__ == '__main__':
    ff = MmRSTrend()
    ff.add_params(F='1d')
