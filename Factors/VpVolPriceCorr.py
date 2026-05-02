# =============================================================================
# Factors/VpVolPriceCorr.py
# 量价相关性因子
#
# FactorFamily 表达式驱动版本。
# r_t = (P_t - P_{t-RF}) / P_{t-RF}
# X_t = Corr(V, r, N)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class VpVolPriceCorr(FactorFamily):
    """量价相关性。"""

    source_freq = 'MIN1'

    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        N = WindowParam('N', default_value='20d')
        RF = WindowParam('RF', default_value='1d')

        ret = P.delta(RF)
        vol = DataColumnParam('V', default_value='V')
        return vol.corr(ret, N)

    desc = '量价相关性'
    description = """
## 这是什么
VpVolPriceCorr 是成交量与收益率的滚动相关系数因子，用来衡量价格变化是否得到量能的同步支持。

## 它在看什么
当收益率为正时成交量也倾向放大、收益率为负时成交量也倾向收缩，相关性会偏正；反之，如果下跌放量、上涨缩量，则相关性可能偏负。

## 为什么这个因子可能行得通
量价配合常被视为趋势健康度的重要特征。上涨伴随放量通常意味着买盘认可度更高。

## 使用提醒
相关系数对窗口长度和异常点比较敏感，样本过短时很容易失真。

## 反转信号
量价正相关是健康趋势的标志；当相关性开始脱离正值向 0 或负值演变时，原有趋势的可持续性存疑。
"""

if __name__ == '__main__':
    ff = VpVolPriceCorr()
