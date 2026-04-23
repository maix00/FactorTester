# =============================================================================
# Factors/MmTrend.py
# 线性趋势斜率因子
#
# 在过去 N 个 RF 周期内，对价格序列做线性回归：
#   y_s = α + β * s，s = 0, 1, ..., n-1
#   X_t = β_t / MA_t(P, N)  （用均值归一化，可跨品种比较）
# 正值表示上涨趋势，负值表示下跌趋势。
# =============================================================================
import pandas as pd
import numpy as np
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmTrend(FactorFamily):
    """
    线性趋势斜率因子。

    在 N 期滚动窗口内对价格做最小二乘线性回归，
    取斜率并除以窗口均价归一化，作为趋势强度信号。

    参数：
        P  (DataColumn) : 价格列，默认 CLOSE
        N  (Timedelta)  : 回归窗口长度，默认 20d
        RF (Timedelta)  : 聚合步长，默认 1d
        F  (Timedelta)  : 输出信号频率
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE),
        WindowParam('N', default_value='20d'),
    ]

    chinese_name = '线性趋势斜率'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmTrend 是线性趋势斜率因子。它在最近 N 期价格上拟合一条直线，并用斜率来刻画趋势方向和强度。',
        },
        {
            'title': '它在看什么',
            'body': '如果拟合斜率为正，说明这一窗口里的价格整体在向上倾斜；斜率越大，上升趋势越陡。再用平均价格做归一化后，可以更方便地跨价格水平比较。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '相比只看起点和终点收益，线性回归斜率会利用窗口内全部路径信息，因此对单点异常值不那么敏感。它更接近“价格是否在稳定地沿某个方向推进”，这正是许多趋势策略关心的核心量。',
        },
        {
            'title': '使用提醒',
            'body': '线性趋势默认把窗口内走势近似成一条直线，因此对弯折明显、分段切换频繁的路径解释力有限。',
        },
        {
            'title': '反转信号',
            'body': '线性趋势斜率因子的反转信号包括：（1）斜率绝对值从高位明显回落（斜率拐头）——即趋势还在延续方向，但速度已开始下降；（2）当拟合 R² 很低时，斜率本身的稳定性很差，此时因子信号容易产生反转；（3）价格偏离拟合直线过大时（残差扩大），表明近期有非线性冲击，斜率预测能力会暂时下降。反转在以下情况更有效：趋势明显加速后突然放慢——"速度骤降"比"方向反转"往往更早出现；市场处于关键整数关口或历史高低点附近；时间窗口较短（20d 以下）时斜率稳定性差，反转信号更多。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            \hat{\beta}_t &:= \frac{\sum_s s \cdot y_s - n\bar{s}\bar{y}}{\sum_s s^2 - n\bar{s}^2} \\[5pt]
            X_t &:= \frac{\hat{\beta}_t}{\overline{P}_t}
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('20d'),
                        P: DataColumn = DataColumn.CLOSE, **kwargs) -> pd.Series:
        price = product.MIN1[P]

        def _linslope(x: np.ndarray) -> float:
            n = len(x)
            if n < 2:
                return 0.0
            s = np.arange(n, dtype=float)
            s_mean = s.mean()
            x_mean = x.mean()
            if x_mean == 0:
                return 0.0
            cov = ((s - s_mean) * (x - x_mean)).sum()
            var = ((s - s_mean) ** 2).sum()
            slope = cov / var if var != 0 else 0.0
            return float(slope / x_mean)

        slope_series = price.rolling(N).apply(_linslope, raw=True)
        slope_series = slope_series.fillna(0.0)
        return self.sync_signal(slope_series)
if __name__ == '__main__':
    ff = MmTrend()
    ff.clear_params()
    ff.add_params(F='1d', N='20d')
    ff.add_params(F='1d', N='10d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
