# =============================================================================
# Factors/VlGK.py
# Garman-Klass 波动率因子
#
# FactorFamily 表达式驱动版本。
# hl = ln(H/L); co = ln(C/O)
# X = sqrt(MA(0.5*hl^2 - (2ln2-1)*co^2, N))
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class VlGK(FactorFamily):
    """Garman-Klass 波动率。"""


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
        hl = (h / (l + eps)).log()
        co = (c / (o + eps)).log()
        gk_bar = 0.5 * hl * hl - (2.0 * 0.6931471805599453 - 1.0) * co * co
        return gk_bar.rolling_mean(N).sqrt()

    desc = 'Garman-Klass 波动率'
    description = """
## 这是什么
VlGK 是 Garman-Klass (1980) 波动率估计量，利用日内高低点和开收盘价信息。

## 它在看什么
相比收盘价-收盘价波动率，GK 利用了日内价格路径信息，估计效率约为收盘波动率的 7.4 倍。

## 为什么这个因子可能行得通
信息利用率更高意味着同样数据量下估计更准确，对波动率变化反应更快。

## 使用提醒
GK 假设价格服从几何布朗运动且无跳空。跳空大的品种偏差较大。

## 反转信号
GK 波动率从高位回落代表极端波动消退，市场回归常态。
"""

if __name__ == '__main__':
    ff = VlGK()
    ff.add_params(F='1d')
