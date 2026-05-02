# =============================================================================
# Factors/MmPKTrend.py
# Parkinson 波动趋势因子
#
# FactorFamily 表达式驱动版本。
# PK = (ln(H/L))^2 / (4*ln2); X = mean_N(sign(C-O) * PK)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmPKTrend(FactorFamily):
    """Parkinson 波动趋势因子。\n\n    参数：\n        N (Timedelta) : 天数"""

    source_freq = 'MIN1'

    @staticmethod
    def factor_expr():
        N = WindowParam('N', default_value='10d')
        O = DataColumnParam('O', default_value='OA')
        H = DataColumnParam('H', default_value='HA')
        L = DataColumnParam('L', default_value='LA')
        C = DataColumnParam('C', default_value='CA')
        pk = (H.shift(0) / L.shift(0)).log().abs()
        pk = pk * pk / (4.0 * 0.6931471805599453)  # 4*ln2
        return (pk * (C.shift(0) - O.shift(0)).sign()).ma(N)

    desc = 'PK 波动趋势'
    description = """
## 这是什么
MmPKTrend 是 Parkinson 波动趋势因子，用 PK 估计量度量每日有方向波动强度。

## 它在看什么
PK 仅用 H/L 估计波动，比 C-O 更稳定。

## 为什么这个因子可能行得通
专注于带方向的日内极值区间，对高频价格操纵鲁棒性强。

## 使用提醒
大振幅日权重过高。

## 反转信号
连续高 PK 值后波动均值回归。
"""

if __name__ == '__main__':
    ff = MmPKTrend()
    ff.add_params(F='1d')
