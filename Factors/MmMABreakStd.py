# =============================================================================
# Factors/MmMABreakStd.py
# 标准化均价突破因子
#
# FactorFamily 表达式驱动版本。
# X_t = (P_t - MA(N, P_t)) / STD(N, P_t)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmMABreakStd(FactorFamily):
    """标准化均价突破因子。\n\n    参数：\n        P (DataColumn) : 价格列\n        N (Timedelta)  : 窗口\n        F (Timedelta)  : 信号频率"""


    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        N = WindowParam('N', default_value='10d')
        return (P - P.ma(N)) / (P.std(N) + 1e-10)

    desc = '标准化均价突破'
    description = """
## 这是什么
MmMABreakStd 是标准化均价突破因子，将偏离量除以滚动标准差做归一化。

## 它在看什么
相当于滚动 z-score，适合跨品种比较。

## 为什么这个因子可能行得通
标准化后不同品种间可比，且考虑了近期波动率环境。

## 使用提醒
波动率极端收缩时可能放大微小偏离。

## 反转信号
标准化突破值达到历史极端后，结合成交量萎缩，反转概率上升。
"""

if __name__ == '__main__':
    ff = MmMABreakStd()
    ff.add_params(F='1d')
