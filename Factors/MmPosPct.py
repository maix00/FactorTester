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

    def func_timeseries(self, product: Product, F: Any = pd.Timedelta('5m'),
                        WF: Any = pd.Timedelta('2h'), RF: Any = pd.Timedelta('1d'),
                        P: DataColumn = DataColumn.CLOSE, **kwargs) -> pd.Series:
        ret = product.MIN1[P].pct_change(RF)
        pos_ratio = (ret > 0).rolling(WF).mean()
        return product.MIN1.sync_signal(pos_ratio, F)

if __name__ == '__main__':
    ff = MmPosPct()

    ff.clear_params()
    # ff.add_params(F='5m', RF='1m', WF='5m')
    # ff.add_params(F='15m', RF='1m', WF='15m')
    ff.add_params(F='15m', RF='5m', WF='15m')
    # ff.add_params(F='30m', RF='5m', WF='30m')
    # ff.add_params(F='1d', RF='1d', WF='1d')
    # ff.add_params(F='1d', RF='10min', WF='1d')
    # ff.add_params(F='2d', RF='1d', WF='2d')
    # ff.add_params(F='2d', RF='10min', WF='2d')
    # ff.add_params(F='10d', RF='2d', WF='10d')
    # ff.add_params(F='1d', RF='1d', WF='10d')
    # ff.add_params(F='2d', RF='2d', WF='10d')

    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
    print(fft.products)