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
from tools.parameters import DataColumnParam, FinRangeParam, TimeDeltaParam
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
        DataColumnParam('P', DataColumn.CLOSE),              # 价格列
    ]

    def func_timeseries(self, product: Product, F: Any = pd.Timedelta('1d'),
                        P: DataColumn = DataColumn.CLOSE, **kwargs) -> pd.Series:
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
        # 按 F 聚合，取每组最后一根 bar 的价格
        grouped = product.MIN1[P].groupby(freq=F)
        price = grouped.last()
        # 计算 1 期收益率
        ret = price.pct_change(1)
        # 对齐到信号时间点
        return self.sync_signal(ret, F)

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