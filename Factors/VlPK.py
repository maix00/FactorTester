# =============================================================================
# Factors/VlPK.py
# Parkinson 波动率因子
#
# FactorFamily 表达式驱动版本。
# hl = ln(H/L); X = sqrt(MA(hl^2 / (4ln2), N))
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class VlPK(FactorFamily):
    """Parkinson 波动率。"""


    @staticmethod
    def factor_expr():
        N = WindowParam('N', default_value='14d')
        H = DataColumnParam('H', default_value='HA')
        L = DataColumnParam('L', default_value='LA')
        h = H.shift(0)
        l = L.shift(0)
        eps = 1e-10
        hl = (h / (l + eps)).log()
        pk_bar = hl * hl / (4.0 * 0.6931471805599453)
        return pk_bar.ma(N).sqrt()

    desc = 'Parkinson 波动率'
    description = """
## 这是什么
VlPK 是 Parkinson (1980) 波动率估计量，仅使用日内最高价和最低价。

## 它在看什么
高低点是日内价格极值的充分统计量，包含比收盘价更多的波动信息。估计效率约为收盘波动率的 5.2 倍。

## 为什么这个因子可能行得通
Parkinson 公式简单但有效，对日内振幅的捕捉力强于收盘价波动率。

## 使用提醒
该估计量对涨跌停不敏感——在涨跌停板下高低点被限制，会低估真实波动。

## 反转信号
Parkinson 波动率峰值后急降，是高波动行情结束的领先信号。
"""

if __name__ == '__main__':
    ff = VlPK()
    ff.add_params(F='1d')
