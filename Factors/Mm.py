# =============================================================================
# Factors/Mm.py
# 区间方向动量因子
#
# FactorFamily 表达式驱动版本。
# h_pos=argmax_F(H); l_pos=argmin_F(L); X=dir(H,L) based on h_pos vs l_pos
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class Mm(FactorFamily):
    """区间方向动量因子——最高价与最低价出现先后的方向判断。\n\n    参数：\n        H (DataColumn) : 最高价列\n        L (DataColumn) : 最低价列\n        F (Timedelta) : 信号频率"""


    @staticmethod
    def factor_expr():
        H = DataColumnParam('H', default_value='HA')
        L = DataColumnParam('L', default_value='LA')
        h = H.shift(0)
        l = L.shift(0)
        h_pos = h.argmax('$F')
        l_pos = l.argmin('$F')
        ph = h.rolling_max('$F')
        pl = l.rolling_min('$F')
        up = (ph - pl) / (ph + 1e-10)
        dn = (pl - ph) / (pl + 1e-10)
        return (h_pos > l_pos) * up + (l_pos > h_pos) * dn

    desc = '区间方向动量'
    description = """
## 这是什么
Mm 是区间方向动量因子，观察最近一个信号窗口里最高价和最低价谁先出现谁后出现。

## 它在看什么
h_pos > l_pos = 最高价出现更晚（先探底再涨）= 偏多；反之偏空。

## 为什么这个因子可能行得通
从价格路径的先后顺序判断行情方向，比纯收益率包含更多路径信息。

## 使用提醒
短期震荡时 h_pos 和 l_pos 交替频繁。

## 反转信号
方向信号与价格走势背离是反转前兆。
"""

if __name__ == '__main__':
    ff = Mm()
    ff.add_params(F='1d')
