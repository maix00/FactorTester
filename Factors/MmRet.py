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

from tools.products.Product import Product
from tools import DataColumn
from tools.factors.Factor import FactorFamily
from tools.parameters.Parameter import DataColumnParam, FinRangeParam, TimeDeltaParam
from typing import List, Dict, Any, Sequence, Tuple

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
        DataColumnParam('P', DataColumn.CLOSE),             # 价格列
        TimeDeltaParam('F', flag='pos', default_value='1d'), # 信号/聚合频率
    ]

    def func(self, products: Sequence[Product], F: Any = pd.Timedelta('1d'),
             P: DataColumn = DataColumn.CLOSE, **kwargs) -> pd.DataFrame:
        """
        批量计算 MmRet 因子。

        流程：
          1. 调用 _get_data 获取按频率 F 分组的数据
          2. 取每组最后一根 bar 的 P 列值
          3. 计算相邻组之间的 pct_change（即 1 期动量）

        参数：
            products : 品种列表
            F        : 聚合频率
            P        : 价格列

        返回：
            DataFrame，列为 Product，索引为信号时间戳 MultiIndex
        """
        factors = {}
        for product in products:
            # _get_data 返回 (data, info)，info['grouped'] 为按 F 分组的 DataFrameGroupBy
            _, info = product.MIN1._get_data(self,
                extra_time_col_freq=F,
                extra_time_col_bfill=True,
                extra_time_col_groupby=True)
            df_grouped = info['grouped']
            # 取每组最后一根 bar 的收盘价，再计算 1 期 pct_change
            factors[product] = df_grouped.last()[P.name].pct_change(1)

        return pd.DataFrame(factors)

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