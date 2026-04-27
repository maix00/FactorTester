# =============================================================================
# Factors/MmCCI.py
# 顺势指标因子（CCI）
#
# 在过去 N 个 RF 周期内，典型价格与其简单移动均值的偏差：
#   TP_t = (H_t + L_t + C_t) / 3
#   X_t = (TP_t - MA_t(TP, N)) / (0.015 * MAD_t(TP, N))
# 高值表示价格显著高于近期均值（上涨动能），低值表示下跌动能。
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class MmCCI(FactorFamily):
    """
    顺势指标因子（Commodity Channel Index）。

    典型价格 TP = (HIGH + LOW + CLOSE) / 3，
    在 N 期窗口内计算 TP 与其均值的偏差除以标准差：
      X_t = (TP_t - MA(TP, N)) / (0.015 * STD(TP, N))

    参数：
        N  (Timedelta) : 滚动窗口长度，默认 20d
        F  (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N', default_value='20d'),
    ]

    chinese_name = '商品通道指数'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmCCI 是经典的商品通道指数类因子。它比较当前典型价格相对其滚动均值的偏离程度，并用平均绝对偏差做标准化。',
        },
        {
            'title': '它在看什么',
            'body': '如果当前价格明显高于近期平均水平，CCI 会变大；若明显低于平均水平，则会变小。由于分母使用的是同一窗口内的平均绝对偏差，因子不仅衡量偏离方向，也衡量“偏离是否已经超过这个市场近期正常波动范围”。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '当价格偏离其局部均衡过多时，市场常出现两类行为：趋势市场里，强偏离可能代表趋势加速；震荡市场里，强偏离可能代表过度扩张后回归。CCI 的价值在于把“相对均衡的偏离幅度”显式量化出来，适合与其他趋势或波动率因子联用。',
        },
        {
            'title': '使用提醒',
            'body': 'CCI 对窗口长度和市场状态较敏感。在强趋势环境里，高位或低位可能持续很久；在均值回归环境里，同样的极端值更容易回落。',
        },
        {
            'title': '反转信号',
            'body': '当 CCI 进入极端区域（常用阈值如 ±100 或 ±200）后，反转信号的参考价值上升：（1）在震荡市里，高 CCI 往往是阶段性顶部的前兆，低 CCI 对应阶段性底部；（2）反转在以下情况更有效：成交量无法配合极端 CCI 方向（量价背离）；RSI 等其他指标同步显示超买超卖；近期波动率中枢没有同步抬升。趋势市中，高 CCI 持续时间可以很长，直接用 CCI 做反转可能频繁止损，此时建议先确认趋势格局是否已出现疲竭。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            TP_t &:= \frac{HA_t + LA_t + CA_t}{3} \\[5pt]
            X_t  &:= \frac{TP_t - \mathrm{RollingMean}_{N}(TP)_t}{0.015 \cdot \mathrm{RollingSTD}_{N}(TP)_t}
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('20d'), **kwargs) -> pd.Series:
        high  = product.MIN1[DataColumn.HIGH_ADJUSTED]
        low   = product.MIN1[DataColumn.LOW_ADJUSTED]
        close = product.MIN1[DataColumn.CLOSE_ADJUSTED]
        tp = (high + low + close) / 3.0
        ma  = tp.rolling(N).mean()
        mad = tp.rolling(N).std()
        cci = (tp - ma) / (0.015 * mad.replace(0, float('nan')))
        cci = cci.fillna(0.0)
        return self.sync_signal(cci)
    
if __name__ == '__main__':
    ff = MmCCI()
    ff.clear_params()
    ff.add_params(F='1d', N='20d')
    ff.add_params(F='1d', N='10d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
