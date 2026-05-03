# =============================================================================
# Factors/MmSkew.py
# 收益率偏度因子
#
# FactorFamily 表达式驱动版本。
# X_t = Skew_N(r) where r = (P_t - P_{t-RF}) / P_{t-RF}
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmSkew(FactorFamily):
    """收益率偏度因子。\n\n    参数：\n        P (DataColumn) : 价格列\n        N (Timedelta)  : 偏度窗口\n        RF (Timedelta) : 收益步长"""


    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        N = WindowParam('N', default_value='20d')
        RF = WindowParam('RF', default_value='1d')
        r = P.delta(RF) / P.shift(RF)
        return r.skew(N)

    desc = '收益率偏度'
    description = """
## 这是什么
MmSkew 是收益率偏度因子，衡量收益分布是否更偏向大涨还是大跌。

## 它在看什么
正偏度 = 右偏 = 偶发大涨为主；负偏度 = 左偏 = 偶发大跌为主。

## 为什么这个因子可能行得通
偏度反映市场参与者的不对称行为——恐慌性下跌 vs 冲动性追涨。

## 使用提醒
偏度在小样本下估计不稳定，需要足够长的窗口。

## 反转信号
极端正偏度通常意味着市场情绪过热，之后均值回归概率上升。
"""

if __name__ == '__main__':
    ff = MmSkew()
    ff.add_params(F='1d')
