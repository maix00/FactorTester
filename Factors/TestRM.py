import pandas as pd
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Products import Product, DataColumn
from Factor import FactorFamily
from Parameter import DataColumnParam, TimeDeltaParam
from typing import Sequence, Any

class MmPosPct(FactorFamily):  # 上涨天数占比（胜率）

    params = [
        DataColumnParam('P', DataColumn.CLOSE),
        TimeDeltaParam('WF', flag='pos', default_value='2h'),      # 时间窗口长度
        TimeDeltaParam('RF', flag='pos', default_value='5m'),      # 计算频率（Return Frequency）
    ]

    def func(self, products: Sequence[Product], F: Any = pd.Timedelta('5m'),
             WF: Any = pd.Timedelta('2h'),
             RF: Any = pd.Timedelta('1d'),
             P: DataColumn = DataColumn.CLOSE, **kwargs) -> pd.DataFrame:
        """
        计算每个产品在过去 F 时间窗口内，按 RF 频率采样得到的正收益占比
        """
        factors = {}
        # 滚动窗口周期数 = F 包含的 RF 个数（向下取整，至少为1）
        window = max(1, int(WF / RF))

        for product in products:
            # 因子频率为 F, 按 F 得到最终的时序点，但在计算过程中按 RF 频率采样得到价格序列
            seq, info = product.MIN1._get_data(self, extra_time_col_freq=F)
            res_idx = seq.index.droplevel([l for l in seq.index.names if l not in info['groupby_index']]).unique()

            # 按 RF 重采样，得到每个采样点的收盘价
            _, info = product.MIN1._get_data(
                self,
                extra_time_col_freq=RF,
                extra_time_col_bfill=True,
                extra_time_col_groupby=True
            )
            df_grouped = info['grouped']
            close_series = df_grouped.last()[P.name]
            # 计算收益率
            ret_series = close_series.pct_change(1)
            # 滚动窗口内正收益占比
            pos_ratio = ret_series.rolling(window=window, min_periods=window).apply(
                lambda x: (x > 0).sum() / len(x)
            )
            factors[product] = pos_ratio

        return pd.DataFrame(factors)


if __name__ == '__main__':
    ff = MmPosPct()
    # ff.add_params(F='10d', RF='1d')
    # ff.add_params(F='5d', RF='1d')
    # ff.add_params(F='3d', RF='1d')
    # ff.add_params(F='2d', RF='1d')
    # # 示例：10小时窗口，每小时采样一次
    # ff.add_params(F='10h', RF='1h')

    from Parameter import Parameter
    print(Parameter[0])
    ff.clear_params()
    ff.add_params(F='5m', RF='1m', WF='5m')

    fft = ff.test(start_cal_time=('1min', '2024-01-03 09:00:00'))
    print(fft.products)