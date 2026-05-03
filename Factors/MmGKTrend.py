# =============================================================================
# Factors/MmGKTrend.py
# Garman-Klass 波动趋势因子
#
# FactorFamily 表达式驱动版本。
# GK = 0.5*(ln(H/L))^2 - (2*ln2-1)*(ln(C/O))^2; X = mean_N(sign(C-O) * GK)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmGKTrend(FactorFamily):
    """Garman-Klass 波动趋势因子。\n\n    参数：\n        N (Timedelta) : 天数"""


    @staticmethod
    def factor_expr():
        N = WindowParam('N', default_value='10d')
        O = DataColumnParam('O', default_value='OA')
        H = DataColumnParam('H', default_value='HA')
        L = DataColumnParam('L', default_value='LA')
        C = DataColumnParam('C', default_value='CA')
        hl = (H.shift(0) / L.shift(0)).log()
        co = (C.shift(0) / O.shift(0)).log()
        gk = 0.5 * hl * hl - (2.0 * 0.6931471805599453 - 1.0) * co * co  # 2*ln2-1
        return (gk * co.sign()).ma(N)

    desc = 'GK 波动趋势'
    description = """
## 这是什么
MmGKTrend 是 Garman-Klass 波动趋势因子，利用 GK 估计量度量每日有方向波动强度。

## 它在看什么
GK 结合 H/L 和 C/O 信息，比纯 PK 偏差更小。

## 为什么这个因子可能行得通
GK 是最优的无偏波动估计量之一，加入方向后信号更丰富。

## 使用提醒
对跳空缺口敏感。

## 反转信号
GK 趋势在高位走平且日内走势开始反向。
"""

if __name__ == '__main__':
    ff = MmGKTrend()
    ff.add_params(F='1d')
