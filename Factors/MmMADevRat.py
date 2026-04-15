import pandas as pd
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn
from tools.products.Product import Product
from tools.factors.Factor import FactorFamily
from tools.parameters.Parameter import DataColumnParam, TimeDeltaParam
from typing import Any

class MmMADevRat(FactorFamily): # Momemtum Moving Average Deviation Ratio
    """
    均线偏离比值因子：过去 N 日的移动平均与收盘价比值的相反数。

    .. math::
        X_t = -\\frac{MA_t(N)}{P_t}, \\quad MA_t(N) = \\frac{1}{N}\\sum_{i=0}^{N-1} P_{t-i}
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE),          # 价格列
        TimeDeltaParam('N', flag='pos', default_value='5d'),   # 移动平均窗口长度
        # 保留 RF 参数以保持接口一致，但在本因子中不使用
        TimeDeltaParam('RF', flag='pos', default_value='1d'),
    ]

    math_expr = r'''
        \begin{aligned}
            MA_t(N) &:= \frac{1}{N}\sum_{i=0}^{N-1} P_{t-i} \\
            X_t &:= -\frac{MA_t(N)}{P_t}
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, F: Any = pd.Timedelta('1d'),
                        N: Any = pd.Timedelta('5d'), RF: Any = pd.Timedelta('1d'),
                        P: DataColumn = DataColumn.CLOSE, **kwargs) -> pd.Series:
        """
        计算均线偏离比值因子。

        Parameters
        ----------
        product : Product
            产品对象
        F : Any, default=pd.Timedelta('1d')
            输出频率
        N : Any, default=pd.Timedelta('5d')
            移动平均窗口长度
        RF : Any, default=pd.Timedelta('1d')
            未使用，为保持接口一致而保留
        P : DataColumn, default=DataColumn.CLOSE
            使用的价格列

        Returns
        -------
        pd.Series
            按频率 F 同步后的因子序列
        """
        # 1. 获取价格序列（1分钟分辨率）
        price = product.MIN1[P]

        # 2. 计算滚动窗口内的简单移动平均
        ma = price.rolling(N).mean()

        # 3. 计算 -MA/P
        ratio = -ma / price

        # 4. 处理无穷大或缺失值（例如价格为零时）
        ratio = ratio.replace([float('inf'), -float('inf')], float('nan')).fillna(0.0)

        # 5. 同步到目标频率并返回
        return product.MIN1.sync_signal(ratio, F)


if __name__ == '__main__':
    ff = MmMADevRat()

    ff.clear_params()

    # 参数组合示例
    ff.add_params(F='1d', N='5d')           # 日频输出，5日均线偏离
    ff.add_params(F='1d', N='10d')          # 日频输出，10日均线偏离
    ff.add_params(F='1h', N='5d')           # 小时频输出，5日均线偏离（每个小时计算一次）
    ff.add_params(F='1d', N='20d')          # 日频输出，20日均线偏离
    ff.add_params(F='15m', N='2h')          # 15分钟输出，2小时均线偏离（非整数天窗口）

    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
    print(fft.products)