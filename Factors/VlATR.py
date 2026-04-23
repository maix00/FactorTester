# =============================================================================
# Factors/VlATR.py
# 平均真实波幅因子（ATR）
#
# N 期内真实波幅的滚动均值，归一化为价格的百分比：
#   TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)
#   X_t = MA(TR, N) / C_t
# 高值表示近期波动率大，低值表示市场平静。
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily, max
from tools.parameters import WindowParam


class VlATR(FactorFamily):
    """
    平均真实波幅因子（Average True Range）。

    计算 N 期滚动 ATR 并除以当期收盘价归一化，
    反映近期价格波动的相对幅度。

    参数：
        N (Timedelta) : 滚动窗口，默认 14d
        F (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N', default_value='14d'),
    ]

    chinese_name = '真实波幅'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'VlATR 是平均真实波幅类因子，用真实波动范围的滚动均值来刻画市场近期波动强度，并通常按价格水平做归一化。',
        },
        {
            'title': '它在看什么',
            'body': 'ATR 不只看当期高低价差，还会把相对前一时点的跳空纳入考虑，因此比简单振幅更能反映真实交易风险。因子上升通常表示波动环境在变激烈。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '波动率是最基本的市场状态变量之一。趋势启动、风险释放、流动性恶化和事件冲击，都会先体现在真实波动范围扩张上。ATR 因此不仅可用于风险控制，也常能辅助判断因子在什么环境下更有效。',
        },
        {
            'title': '使用提醒',
            'body': 'ATR 更偏环境刻画而非纯方向信号。若直接用于排序，通常要明确自己是在押注高波动溢价、低波动延续，还是把它作为过滤器。',
        },
        {
            'title': '反转信号',
            'body': 'ATR 类波动率因子本身不直接预测方向，但与反转的关系如下：（1）ATR 快速从低位抬升（波动率扩张），通常意味着市场正在消化新信息，此时方向不明，原有趋势容易出现反转；（2）ATR 处于历史极高位后快速回落（波动率收缩），意味着大幅震荡结束，市场往往在方向上重新选择，可以配合其他方向性因子共同入场；（3）价格突破但 ATR 未放大（低波动率突破），往往是假突破的前兆，反转概率更高。实践中，高 ATR 区间通常不宜直接做反转，而应等待 ATR 开始收缩，方向性信号稳定后再操作。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            TR_t &:= \max(H_t - L_t,\; |H_t - C_{t-1}|,\; |L_t - C_{t-1}|) \\[5pt]
            X_t  &:= \frac{MA(TR,\, N)_t}{C_t}
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('14d'), **kwargs) -> pd.Series:
        high  = product.MIN1[DataColumn.HIGH]
        low   = product.MIN1[DataColumn.LOW]
        close = product.MIN1[DataColumn.CLOSE]
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low  - prev_close).abs()
        tr = max(tr1, tr2, tr3)
        atr = tr.rolling(N).mean()
        factor = atr / close.replace(0, float('nan'))
        factor = factor.fillna(0.0)
        return self.sync_signal(factor)
    
if __name__ == '__main__':
    ff = VlATR()
    ff.clear_params()
    ff.add_params(F='1d', N='14d')
    ff.add_params(F='1d', N='7d')
    ff.add_params(F='1d', N='21d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
