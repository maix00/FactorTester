# =============================================================================
# Factors/MmIntradayRange.py
# 日内累计振幅因子
#
# FactorFamily 表达式驱动版本。
# step = (2(H-L)*sign(C-O) - (C-O)) / C; X = mean_N(step)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmIntradayRange(FactorFamily):
    """日内累计振幅因子。\n\n    参数：\n        N (Timedelta) : 天数"""


    @staticmethod
    def factor_expr():
        N = WindowParam('N', default_value='10d')
        O = DataColumnParam('O', default_value='OA')
        H = DataColumnParam('H', default_value='HA')
        L = DataColumnParam('L', default_value='LA')
        C = DataColumnParam('C', default_value='CA')
        step = (2.0 * (H.shift(0) - L.shift(0)) * (C.shift(0) - O.shift(0)).sign() - (C.shift(0) - O.shift(0))) / (C.shift(0) + 1e-10)
        return step.rolling_mean(N)

    desc = '日内累计振幅'
    description = """
## 这是什么
MmIntradayRange 是日内累计振幅因子，捕捉方向性扩张的程度。

## 它在看什么
上涨日的振幅贡献为正，下跌日为负，比纯日内收益率包含更多路径信息。

## 为什么这个因子可能行得通
趋势行情通常伴随方向性振幅扩张（大涨日振幅大、大跌日振幅大）。

## 使用提醒
窄幅整理期信号较弱。

## 反转信号
极大振幅后次日振幅急剧收缩往往是动能衰竭信号。
"""

if __name__ == '__main__':
    ff = MmIntradayRange()
    ff.add_params(F='1d')
