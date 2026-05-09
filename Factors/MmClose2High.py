# =============================================================================
# Factors/MmClose2High.py
# 收盘价区间位置因子
#
# FactorFamily 表达式驱动版本。
# X_t = (C_t - min_N(L_t)) / (max_N(H_t) - min_N(L_t))
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmClose2High(FactorFamily):
    """收盘价区间位置（Williams %R 正向化版本）。\n\n    参数：\n        N (Timedelta) : 回看窗口"""


    @staticmethod
    def factor_expr():
        N = WindowParam('N', default_value='14d')
        C = DataColumnParam('P', default_value='CA')
        H = DataColumnParam('H', default_value='HA')
        L = DataColumnParam('L', default_value='LA')
        h_max = H.rolling_max(N).as_intermediate('Hmax')
        l_min = L.rolling_min(N).as_intermediate('Lmin')
        rng = h_max - l_min
        return (C - l_min) / (rng + 1e-10)

    desc = '收盘价区间位置'
    description = """
## 这是什么
MmClose2High 是收盘价区间位置因子，衡量当前收盘价在最近一段高低区间中的相对位置。

## 它在看什么
C 在 [L_min, H_max] 中越偏上，因子越接近 1；越偏下越接近 0。

## 为什么这个因子可能行得通
高位收盘本身有趋势确认的含义；低位收盘则反之。

## 使用提醒
窄幅横盘时因子敏感度高，容易产生假突破信号。

## 反转信号
极端高位连续多日不创新高 + 成交量锐减 = 高位疲软。
"""

if __name__ == '__main__':
    ff = MmClose2High()
    ff.add_params(F='1d')
