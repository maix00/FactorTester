# =============================================================================
# Factors/VlATR.py
# 平均真实波幅因子
#
# FactorFamily 表达式驱动版本。
# TR = max(H-L, |H-C_1|, |L-C_1|); X = MA(TR,N) / C
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class VlATR(FactorFamily):
    """平均真实波幅因子。"""


    @staticmethod
    def factor_expr():
        N = WindowParam('N', default_value='14d')
        H = DataColumnParam('H', default_value='HA')
        L = DataColumnParam('L', default_value='LA')
        C = DataColumnParam('C', default_value='CA')
        h = H.shift(0)
        l = L.shift(0)
        c = C.shift(0)
        prev_c = c.shift(1)
        tr1 = h - l
        tr2 = (h - prev_c).abs()
        tr3 = (l - prev_c).abs()
        tr = tr1.max(tr2).max(tr3)
        return tr.ma(N) / (c + 1e-10)

    desc = '真实波幅'
    description = """
## 这是什么
VlATR 是 Wilder 平均真实波幅除以收盘价，得到归一化的波动率度量。

## 它在看什么
真实波幅同时考虑了当日振幅、跳空缺口和前一日的延续范围。除以收盘价使其跨品种可比。

## 为什么这个因子可能行得通
ATR 是业界标准的波动率指标，对趋势加速和波动突变都非常敏感。

## 使用提醒
高 ATR 值既可以出现在趋势中（健康放大），也可以出现在恐慌中（质量差）。需结合方向信号使用。

## 反转信号
ATR 冲高后回落，常代表情绪释放完毕，价格可能进入盘整或反转。
"""

if __name__ == '__main__':
    ff = VlATR()
    ff.add_params(F='1d')
