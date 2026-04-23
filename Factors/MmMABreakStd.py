# =============================================================================
# Factors/MmMABreakStd.py
# 标准化均价突破因子
#
# 用价格的 N 期滚动标准差对均价突破进行归一化：
#   X_t = (P_t - MA(N, P_t)) / std(P, N)
# 类似 z-score，衡量价格突破均线的"幅度相对于历史波动"的倍数，
# 适合跨品种横截面比较，解决了 MmMABreak 的量纲问题。
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmMABreakStd(FactorFamily):
    """
    标准化均价突破因子。

    将均价突破量（Pt - MA(N)）除以同期的 N 期价格滚动标准差，
    得到量纲无关、可跨品种比较的标准化突破信号（z-score 形式）。

    参数：
        P  (DataColumn) : 价格列，默认 CLOSE
        N  (Timedelta)  : 均线和标准差的回看窗口，默认 10d
        F  (Timedelta)  : 输出信号频率
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE),
        WindowParam('N', default_value='10d'),
    ]

    chinese_name = '标准化均价突破'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmMABreakStd 是标准化均价突破因子，将价格突破均线的绝对量除以价格的 N 期滚动标准差，使结果以"标准差"为单位，可以直接跨品种比较：因子值 2 表示价格高于均线 2 个标准差，无论原始价格是多少都具有相同含义。',
        },
        {
            'title': '它在看什么',
            'body': '它衡量的是"价格对历史均值的偏离，相对于该品种自身波动幅度的比例"。本质上是一个滚动 z-score，能区分"铁矿突破了 10 元均线但月波动 50 元（突破不显著）"和"铜突破了 100 元均线且月波动仅 80 元（突破极显著）"这两种对截面动量影响完全不同的情况。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '标准化后的突破量在统计意义上更稳定：历史上该品种"突破 2 个标准差"的事件，其后趋势延续的概率比"突破 0.5 个标准差"更高。同时，标准化解决了跨品种横截面比较的量纲问题，是直接替代 MmMABreak 用于截面排名/多品种组合的推荐版本。',
        },
        {
            'title': '使用提醒',
            'body': '标准差分母在低波动率期间可能接近零，导致因子值异常放大；建议设置最小波动率门槛加护盾。另外，均值和标准差用相同的 N 期窗口，这使得因子对窗口长度的敏感性高于 MmMABreak，N 的选择需要更谨慎。',
        },
        {
            'title': '反转信号',
            'body': '当因子值超过 ±2 至 ±3 个标准差时，从统计角度已进入极端区间，均值回归概率显著上升——这不是预测反转的充分条件，但可以作为多头持仓减仓或设置止损的参考阈值；因子在高位出现连续多周期下降（突破幅度收窄），往往比价格本身更早发出趋势减弱的信号。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            X_t &:= \frac{P_t - \overline{P}_N}{\sigma_N(P)}.
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('10d'),
                        P: DataColumn = DataColumn.CLOSE, **kwargs) -> pd.Series:
        price = product.MIN1[P]
        ma    = price.rolling(N).mean()
        std   = price.rolling(N).std().replace(0, float('nan'))
        factor = ((price - ma) / std).fillna(0.0).replace([float('inf'), -float('inf')], 0.0)
        return self.sync_signal(factor)

if __name__ == '__main__':
    ff = MmMABreakStd()
    ff.clear_params()
    ff.add_params(F='1d', N='10d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
