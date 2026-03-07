import numpy as np
import pandas as pd
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from CNFutures import CNFutures
from Products import Product, DataColumn
from FactorTester import FactorFamily, DataColumnParam, FinRangeParam
from typing import List, Dict, Any, Sequence, Tuple

class Mm(FactorFamily): # Day Momentum

    additional_params = [
        DataColumnParam('H').set_default_value(DataColumn.HIGH),
        DataColumnParam('L').set_default_value(DataColumn.LOW),
        FinRangeParam('F', ['1d', 'S', '5h', '3h']).set_default_value('1d')
    ]

    def funcMIN1(self, products: Sequence[Product],
             H: DataColumn = DataColumn.HIGH,
             L: DataColumn = DataColumn.LOW, **kwargs) -> pd.DataFrame:
        factors = {}
        for product in products:
            _H = product.get_col_name(H)
            df = product.get_data('1min')[_H]
            factors[product] = df
        return pd.DataFrame(factors)
    
    def funcMIN5(self, products: Sequence[Product],
             H: DataColumn = DataColumn.HIGH,
             L: DataColumn = DataColumn.LOW, **kwargs) -> pd.DataFrame:
        factors = {}
        for product in products:
            _H = product.get_col_name(H)
            df = product.get_data('1min')[_H]
            factors[product] = df[4::5]
        return pd.DataFrame(factors)

    def func1(self, products: Sequence[Product],
             H: DataColumn = DataColumn.HIGH_ADJUSTED,
             L: DataColumn = DataColumn.LOW_ADJUSTED, **kwargs) -> pd.DataFrame:
        factors = {}
        for product in products:
            df = product.get_data('1min')
            _H = product.get_col_name(H)
            _L = product.get_col_name(L)
            _TD = product.get_col_name(DataColumn.TIME_COL_DAY)
            day_high = df[_H].groupby(_TD).max()
            day_low = df[_L].groupby(_TD).min()
            idx_high = df[_H].groupby(_TD).idxmax()
            idx_low = df[_L].groupby(_TD).idxmin()
            mask = idx_low < idx_high
            temp_high = day_high.copy()
            day_high.loc[mask] = day_low.loc[mask]
            day_low.loc[mask] = temp_high.loc[mask]
            factors[product] = (day_high - day_low) / day_high
        return pd.DataFrame(factors)
    
    
    def func(self, products: Sequence[Product], F: str = '1d',
             H: DataColumn = DataColumn.HIGH,
             L: DataColumn = DataColumn.LOW, **kwargs) -> pd.DataFrame:
        factors = {}
        for product in products:
            if not isinstance(product, CNFutures):
                continue
            df = product.get_data('1min')
            _H = product.get_col_name(H)
            _L = product.get_col_name(L)
            _TD = product.get_col_name(DataColumn.TIME_COL_DAY)
            _TM = product.get_col_name(DataColumn.TIME_COL_MIN)

            day_high = df[_H].groupby(_TD).max()
            day_low = df[_L].groupby(_TD).min()
            idx_high = df[_H].groupby(_TD).idxmax()
            idx_low = df[_L].groupby(_TD).idxmin()

            if F == '1d':
                pass
            elif F == 'S':
                _TD_ = df.index.get_level_values(_TD).to_series().reset_index(drop=True)
                _TM_ = df.index.get_level_values(_TM).to_series().reset_index(drop=True)
                time_part = _TM_.dt.time
                cond = (time_part >= pd.Timestamp('09:00').time()) & (time_part <= pd.Timestamp('15:00').time())
                end_session = _TD_ + pd.Timedelta('9 hours')
                end_session[cond] = _TD_[cond] + pd.Timedelta('15 hours')
                df.index = pd.MultiIndex.from_arrays([_TD_, end_session], names=[_TD, 'end_session'])
                df_grouped = df.groupby([_TD, 'end_session'])

                day_high = df_grouped[_H].max()
                day_low = df_grouped[_L].min()
                idx_high = df_grouped[_H].idxmax()
                idx_low = df_grouped[_L].idxmin()

            mask = idx_low < idx_high
            temp_high = day_high.copy()
            day_high.loc[mask] = day_low.loc[mask]
            day_low.loc[mask] = temp_high.loc[mask]
            factors[product] = (day_high - day_low) / day_high
        return pd.DataFrame(factors)

if __name__ == '__main__':
    ff = Mm()
    ff.change_default_return_freq('5h')
    ff.add_params(F = 'S')
    ff.test(categories=['农产品'])