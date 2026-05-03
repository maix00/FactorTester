# =============================================================================
# Factors/MmDMI.py
# 方向性动量指标因子
#
# FactorFamily 表达式驱动版本。
# +DI/-DI 基于 TR/+DM/-DM 的 N 期滚动和计算，X=(+DI--DI)/(+DI+-DI)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmDMI(FactorFamily):
    """方向性动量指标（DMI/DX）。\n\n    参数：\n        N (Timedelta) : 滚动窗口"""


    @staticmethod
    def factor_expr():
        N = WindowParam('N', default_value='14d')
        H = DataColumnParam('H', default_value='HA')
        L = DataColumnParam('L', default_value='LA')
        C = DataColumnParam('C', default_value='CA')
        h = H.shift(0)
        l = L.shift(0)
        c = C.shift(0)
        prev_h = h.shift(1)
        prev_l = l.shift(1)
        prev_c = c.shift(1)
        # True Range: max(H-L, |H-C_1|, |L-C_1|)
        tr1 = h - l
        tr2 = (h - prev_c).abs()
        tr3 = (l - prev_c).abs()
        tr = tr1.max(tr2).max(tr3)
        # +DM / -DM
        up_move = h - prev_h
        down_move = prev_l - l
        pdm = ((up_move + up_move.abs()) / 2.0) * (up_move > down_move)
        ndm = ((down_move + down_move.abs()) / 2.0) * (down_move > up_move)
        # +DI / -DI
        tr_sum = tr.rolling_sum(N)
        pdi = pdm.rolling_sum(N) / (tr_sum + 1e-10)
        ndi = ndm.rolling_sum(N) / (tr_sum + 1e-10)
        # DX
        return (pdi - ndi) / (pdi + ndi + 1e-10)

    desc = '方向性动量指标'
    description = """
## 这是什么
MmDMI 是方向性动量因子，把向上运动和向下运动分别提取出来，用真实波动范围做标准化。

## 它在看什么
当正向方向运动持续强于负向时因子上升，反之下降。强调"净方向性"而非单纯涨跌幅。

## 为什么这个因子可能行得通
有效趋势通常体现为高点不断抬升、低点同步上移。DMI 分离方向性推进与噪声波动。

## 使用提醒
高波动震荡中可能反复来回切换，需配合趋势过滤使用。

## 反转信号
+DI 和 -DI 之差从极端值收敛是趋势衰竭的早期信号；交叉是传统反转信号。
"""

if __name__ == '__main__':
    ff = MmDMI()
    ff.add_params(F='1d')
