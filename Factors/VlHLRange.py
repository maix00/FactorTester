# =============================================================================
# Factors/VlHLRange.py
# 高低点区间比因子
#
# FactorFamily 表达式驱动版本。
# X = MA((H-L) / mid, N) where mid=(H+L)/2
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class VlHLRange(FactorFamily):
    """高低点区间比因子。"""

    source_freq = 'MIN1'

    @staticmethod
    def factor_expr():
        N = WindowParam('N', default_value='10d')
        H = DataColumnParam('H', default_value='HA')
        L = DataColumnParam('L', default_value='LA')
        h = H.shift(0)
        l = L.shift(0)
        mid = (h + l) / 2.0
        hl_range = (h - l) / (mid + 1e-10)
        return hl_range.ma(N)

    desc = '高低点区间比'
    description = """
## 这是什么
VlHLRange 是周期内高低点振幅相对于中点的比值，再做移动平均。

## 它在看什么
相对振幅放大意味着市场在该时期波动加剧，争夺激烈。均值化后得到延续的波动状态。

## 为什么这个因子可能行得通
大振幅往往伴随流动性消耗——方向选择前的征兆。连续大振幅后缩小往往是突破的启动点。

## 使用提醒
该因子对跳空开盘敏感。需要结合成交量确认振幅是否"真实"。

## 反转信号
区间比从高位收敛至低位后，多空某一方可能已获胜，形成方向性突破。
"""

if __name__ == '__main__':
    ff = VlHLRange()
    ff.add_params(F='1d')
