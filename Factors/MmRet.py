# =============================================================================
# Factors/MmRet.py
# 收益率动量因子
#
# MmRet 计算过去 F 期内的价格涨跌幅（动量），使用 1 分钟数据聚合后计算：
#   X_t = (P_t - P_{t-F}) / P_{t-F}
# 参数：P（价格列）、F（信号频率）
# =============================================================================
import pandas as pd
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam
from typing import Any

class MmRet(FactorFamily):
    """
    收益率动量因子（Momentum of Return）。

    按频率 F 将 1 分钟 K 线聚合为周期 K 线，取每个周期最后一个收盘价，
    计算相邻两个周期的收益率作为因子值。

    参数：
        P (DataColumn) : 价格列，默认 CLOSE
        F (Timedelta)  : 信号频率（聚合周期），默认 '1d'
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE_ADJUSTED),              # 价格列
    ]

    chinese_name = '收益率动量'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmRet 是最直接的收益率动量因子，计算的是当前价格相对一个信号频率窗口之前价格的涨跌幅。',
        },
        {
            'title': '它在看什么',
            'body': '如果最近一个 `$F` 周期上涨，因子为正；下跌则为负。它没有额外平滑、路径分解或成交量权重，因此可以看作许多更复杂动量因子的基准版本。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '如果市场存在最基本的趋势惯性，那么最近一期或最近一个窗口的收益方向本身就带有预测信息。MmRet 的优势在于解释直接、实现简单，也便于和其他更复杂的因子做增量比较。',
        },
        {
            'title': '使用提醒',
            'body': 'MmRet 也最容易受到短期反转影响。周期太短时会更像噪声和微观结构；周期太长时则会降低信号更新速度。',
        },
        {
            'title': '反转信号',
            'body': '收益率动量最容易在以下场景出现反转：（1）极短周期（如 1-5 分钟）的 MmRet 存在微观结构反转（买单冲击后的价格回归），持仓成本和滑点是主要风险；（2）日线级别连续多日同向后，市场过度拥挤，均值回归力量上升；（3）重要技术位突破失败、假突破后的快速反向是 MmRet 最典型的反转场景。反转信号在以下情况更可靠：量价背离（价格创新高但成交量缩量）；或者价格已显著偏离 VWAP 或关键均线；或者期货升贴水异常快速收敛。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            X_t &:= \frac{P_t - P_{t-F}}{P_{t-F}}
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, P: DataColumn = DataColumn.CLOSE_ADJUSTED, **kwargs) -> pd.Series:
        """
        计算单品种收益率动量因子。

        流程：
          1. 取 P 列的分钟数据，每 F 周期取最后一根 bar 的收盘价（groupby last）
          2. 计算相邻周期的 pct_change（1 期动量）
          3. 对齐到信号时间点并返回

        参数：
            product : 品种对象
            F       : 聚合/信号频率
            P       : 价格列

        返回：
            按频率 F 同步后的 pd.Series
        """
        F = kwargs.get('F', kwargs.get('$F', pd.Timedelta('1d')))
        # 直接在分钟数据上计算跨 F 周期的收益率，避免 groupby
        price = product.MIN1[P]
        ret = price.pct_change(F)
        # 对齐到信号时间点
        return self.sync_signal(ret)
if __name__ == '__main__':
    ff = MmRet()
    ff.add_params(F = '10d')
    ff.add_params(F = '5d')
    ff.add_params(F = '3d')
    ff.add_params(F = '2d')
    # # ff.add_params(F = '2min')
    # ff.add_params(F = '5min')
    # ff.add_params(F = '10min')
    # ff.add_params(F = '15min')
    fft = ff.test(start_cal_time=('1min', '2024-01-03 09:00:00'))
    print(fft.products)
    # fft = ff.test(return_freq='6h', start_cal_time=('1min', '2024-01-03 09:00:00'))