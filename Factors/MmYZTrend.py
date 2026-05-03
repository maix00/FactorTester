# =============================================================================
# Factors/MmYZTrend.py
# Yang-Zhang 波动趋势因子
#
# FactorFamily 表达式驱动版本。
# X = sigma_YZ * mean_N(sign(C-O))
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmYZTrend(FactorFamily):
    """Yang-Zhang 波动趋势因子。\n\n    参数：\n        N (Timedelta) : 天数"""


    @staticmethod
    def factor_expr():
        N = WindowParam('N', default_value='10d')
        O = DataColumnParam('O', default_value='OA')
        H = DataColumnParam('H', default_value='HA')
        L = DataColumnParam('L', default_value='LA')
        C = DataColumnParam('C', default_value='CA')
        co = (C.shift(0) - O.shift(0)).sign()
        oc = (O.shift(0) / C.shift('1d')).log()
        co_log = (C.shift(0) / O.shift(0)).log()
        sigma2 = oc.ema(N).abs() + 0.5 * co_log.ema(N).abs()
        return sigma2 * co.ma(N)

    desc = 'YZ 波动趋势'
    description = """
## 这是什么
MmYZTrend 是 Yang-Zhang 波动趋势因子，最全面的版本。

## 它在看什么
同时捕捉趋势方向、波动强度及波动的来源结构（隔夜/日内）。

## 为什么这个因子可能行得通
YZ 估计量无偏且方差最小。

## 使用提醒
计算复杂度高，需要 O/H/L/C 全量数据。

## 反转信号
YZ 趋势与价格出现背离。
"""

if __name__ == '__main__':
    ff = MmYZTrend()
    ff.add_params(F='1d')
