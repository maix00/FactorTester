# =============================================================================
# Factors/MmRateOfChg.py
# 变动率因子（ROC）
#
# 当前价格相对 N 个 RF 周期前价格的变动率：
#   X_t = (P_t - P_{t-N*RF}) / P_{t-N*RF}
# 与 MmRet 的区别：MmRet 是 1 期收益，ROC 是 N 期跨度的长周期收益。
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmRateOfChg(FactorFamily):
    """
    变动率因子（Rate of Change）。

    以 RF 为步长，计算 N 步之前到现在的价格变化率，
    捕捉中等时间跨度的动量信号。

    参数：
        P  (DataColumn) : 价格列，默认 CLOSE
        N  (Timedelta)  : 回看步数（以 RF 为单位的跨度）
        RF (Timedelta)  : 单期步长
        F  (Timedelta)  : 输出信号频率
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE_ADJUSTED),
        WindowParam('N', default_value='10d'),
    ]

    chinese_name = '价格变化率'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmRateOfChg 是标准的价格变化率因子，也就是过去 N 期价格相对 N 期前价格的涨跌幅。',
        },
        {
            'title': '它在看什么',
            'body': '这个因子直接回答一个问题：过去 N 期，这个资产到底涨了多少或跌了多少。它是最朴素也最常见的动量刻画方式。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '在存在趋势延续、信息扩散缓慢、资金分批入场或风险预算调整滞后的市场里，过去一段时间的相对强弱往往会在未来一段时间继续表现出来。价格变化率就是对这种延续性的直接测量。',
        },
        {
            'title': '使用提醒',
            'body': 'ROC 非常基础，因此也最容易受短期冲高回落、事件跳涨跳跌和均值回归影响。通常需要结合窗口长度和其他确认变量一起用。',
        },
        {
            'title': '反转信号',
            'body': '价格变化率（ROC）达到历史极端值后，均值回归往往成为更强的力量：（1）ROC 越极端，短期反转概率越高，这是超卖反弹 / 超买回落的经典机制；（2）反转在以下情况更有效：ROC 的极端来自跳空或单日大阳/大阴线，而非连续温和推进；成交量在极端 ROC 后迅速萎缩；期货持仓量无法跟上方向。若 ROC 处于中间水平（不极端），动量延续概率更高，此时不宜做反转。时间窗口越短，ROC 的反转成分越大；窗口越长，趋势成分越主导。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            X_t &:= \frac{P_t - P_{t - N}}{P_{t - N}}
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('10d'),
                        P: DataColumn = DataColumn.CLOSE_ADJUSTED, **kwargs) -> pd.Series:
        price = product.MIN1[P]
        # pct_change 直接接受 Timedelta，无需 groupby
        roc = price.pct_change(N)
        return self.sync_signal(roc)
if __name__ == '__main__':
    ff = MmRateOfChg()
    ff.clear_params()
    ff.add_params(F='1d', N='10d')
    ff.add_params(F='1d', N='20d')
    ff.add_params(F='1d', N='5d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
