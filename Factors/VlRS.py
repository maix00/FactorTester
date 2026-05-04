# =============================================================================
# Factors/VlRS.py
# Rogers-Satchell 波动率因子
#
# FactorFamily 表达式驱动版本。
# ho=ln(H/O); hc=ln(H/C); lo=ln(L/O); lc=ln(L/C)
# rs = hc*ho + lc*lo; X = sqrt(MA(rs, N))
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class VlRS(FactorFamily):
    """Rogers-Satchell 波动率。"""


    @staticmethod
    def factor_expr():
        N = WindowParam('N', default_value='14d')
        H = DataColumnParam('H', default_value='HA')
        L = DataColumnParam('L', default_value='LA')
        O = DataColumnParam('O', default_value='OA')
        C = DataColumnParam('C', default_value='CA')
        h = H.shift(0)
        l = L.shift(0)
        o = O.shift(0)
        c = C.shift(0)
        eps = 1e-10
        ho = (h / (o + eps)).log()
        hc = (h / (c + eps)).log()
        lo = (l / (o + eps)).log()
        lc = (l / (c + eps)).log()
        rs_bar = hc * ho + lc * lo
        return rs_bar.rolling_mean(N).sqrt()

    desc = 'Rogers-Satchell 波动率'
    description = """
## 这是什么
VlRS 是 Rogers-Satchell (1991) 波动率估计量，利用开高低收四个价格。

## 它在看什么
RS 估计量处理了具有漂移的布朗运动（趋势市场），比 GK 和 PK 更适合趋势市。

## 为什么这个因子可能行得通
在趋势市场中，GK 和 PK 假设价格零漂移会产生偏差。RS 通过交叉项消除漂移影响。

## 使用提醒
RS 在无趋势市场中效率略低于 GK，但在趋势市场中更准确。

## 反转信号
RS 波动率峰值后回归均值，且与价格趋势方向无关——纯粹反映波动强度变化。
"""

if __name__ == '__main__':
    ff = VlRS()
    ff.add_params(F='1d')
