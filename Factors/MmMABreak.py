# =============================================================================
# Factors/MmMABreak.py
# 均价突破因子
#
# 当前价格减去 N 期简单移动平均：
#   X_t = P_t - MA(N, P_t)
# 正值表示价格在均线上方（偏强），负值表示价格在均线下方（偏弱）。
# 与 MmMADevRat（(Pt-MA)/MA 比值）相比，保留价格绝对偏离量，更适合直接做截面比较。
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmMABreak(FactorFamily):
    """
    均价突破因子。

    计算当前价格与 N 期移动平均线之差，衡量当前价格对均线的绝对突破幅度。
    与均线偏离比值（MmMADevRat）相比，不做均线归一化，直接反映绝对偏离。

    参数：
        P  (DataColumn) : 价格列，默认 CLOSE
        N  (Timedelta)  : 均线回看窗口，默认 10d
        F  (Timedelta)  : 输出信号频率
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE),
        WindowParam('N', default_value='10d'),
    ]

    chinese_name = '均价突破'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmMABreak 是均价突破因子，计算当前价格与 N 期简单移动均线的差值，是最经典的均线趋势跟踪信号之一——价格站在均线上方为多头偏强，均线下方为空头偏弱。',
        },
        {
            'title': '它在看什么',
            'body': '它直接衡量价格对历史均值水平的偏离量（以价格为单位），不做任何归一化。绝对值越大，价格与历史平均的背离程度越高。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '均线穿越是趋势交易者最常用的信号源之一：价格突破均线上方是新趋势启动的确认，而价格在均线上方持续运行则是趋势延续的佐证。这个因子能连续地量化这种"突破幅度"，相比简单的均线交叉（只有方向信号）信息量更丰富。',
        },
        {
            'title': '使用提醒',
            'body': '不同品种的价格绝对值相差悬殊（如铁矿 700 元/吨 vs 黄金 500 元/克），直接用绝对差值做截面比较毫无意义；建议配合 MmMABreakStd（标准化版本）使用，或在使用前先对因子按品种做 z-score 标准化。',
        },
        {
            'title': '反转信号',
            'body': '当均价突破因子达到多期历史高位（价格大幅高于均线），且均线斜率开始放缓（均线快速追赶价格），价格与均线的差值快速收窄——这是均值回归启动的典型形态；若均价突破因子在高位短时间内迅速翻负（价格跌破均线），往往伴随较强的动量反转信号，下跌动能可能较猛烈。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            X_t &:= P_t - \frac{1}{N}\sum_{s=0}^{N-1} P_{t-s}.
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('10d'),
                        P: DataColumn = DataColumn.CLOSE, **kwargs) -> pd.Series:
        price = product.MIN1[P]
        ma    = price.rolling(N).mean()
        factor = (price - ma).fillna(0.0)
        return self.sync_signal(factor)

if __name__ == '__main__':
    ff = MmMABreak()
    ff.clear_params()
    ff.add_params(F='1d', N='10d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
