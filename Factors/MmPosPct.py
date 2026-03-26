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
        
        factors = {}

        for product in products:

            ret_series = product.MIN1.groupby(self, freq=RF).last()[P.name].pct_change(1)

            original_index = ret_series.index
            original_index_right = original_index.get_level_values(-1)
            pos_ratio = (ret_series > 0).reset_index(drop=True).to_frame().set_index(original_index_right).rolling(window=WF).mean()
            pos_ratio.index = original_index
            pos_ratio = product.MIN1.groupby(self, data=pos_ratio, freq=F).last()

            if WF.total_seconds() >= pd.Timedelta('1d').total_seconds() \
                and RF.total_seconds() < pd.Timedelta('1d').total_seconds():
                assert WF.total_seconds() % pd.Timedelta('1d').total_seconds() == 0, "WF should be a multiple of 1 day when WF > 1 day."
                pos_ratio = product.MIN1.groupby(self, data=(ret_series > 0), freq=WF).mean().squeeze()
            else:
                window = max(1, int(WF / RF))
                pos_ratio = (ret_series > 0).rolling(window=window, min_periods=window).mean()
            
            index = product.MIN1._get_signal_index(self, freq=F)['signal_index']
            if index.nlevels == pos_ratio.index.nlevels:
                map = pos_ratio.index.isin(index)
                pos_ratio = pos_ratio[map]
            elif index.nlevels < pos_ratio.index.nlevels:
                remained_levels = [l for l in pos_ratio.index.names if l in index.names]
                deleted_levels = [l for l in pos_ratio.index.names if l not in index.names]
                map = pos_ratio.index.droplevel(deleted_levels).isin(index)
                pos_ratio = pos_ratio[map].groupby(level=remained_levels).last()
            else:
                raise ValueError(f"Index levels of pos_ratio ({pos_ratio.index.nlevels}) cannot be matched with signal index ({index.nlevels}).")
            pos_ratio.index = index
            pos_ratio.rename(product.name, inplace=True)

            factors[product] = pos_ratio

        return pd.DataFrame(factors)


if __name__ == '__main__':
    ff = MmPosPct()

    ff.clear_params()
    # ff.add_params(F='5m', RF='1m', WF='5m')
    # ff.add_params(F='15m', RF='1m', WF='15m')
    # ff.add_params(F='15m', RF='5m', WF='15m')
    # ff.add_params(F='30m', RF='5m', WF='30m')
    # ff.add_params(F='1d', RF='1d', WF='1d')
    ff.add_params(F='1d', RF='5min', WF='1d')
    # ff.add_params(F='2d', RF='1d', WF='2d')

    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai', categories=['0'])
    print(fft.products)