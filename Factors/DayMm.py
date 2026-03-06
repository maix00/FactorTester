import numpy as np
import pandas as pd
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Products import Product
from FactorTester import FactorFamily, PriceColumnMapping
from typing import List, Dict, Any, Sequence, Tuple

class DayMm(FactorFamily): # Day Momentum

    params_space: Dict[str, List[Any]] = {
        'PCH': ['HA', 'H'],
        'PCL': ['LA', 'L'],
    }

    def func(self, products: Sequence[Product], data_freq: Any = '1min',
             PCH: str = 'HA', PCL: str = 'LA') -> pd.DataFrame:
        factors = {}
        for product in products:
            df = product.get_data(data_freq)
            day_high = df[PriceColumnMapping[PCH]].groupby('trading_day').max()
            day_low = df[PriceColumnMapping[PCL]].groupby('trading_day').min()
            idx_high = df[PriceColumnMapping[PCH]].groupby('trading_day').idxmax()
            idx_low = df[PriceColumnMapping[PCL]].groupby('trading_day').idxmin()
            mask = idx_low < idx_high
            temp_high = day_high.copy()
            day_high.loc[mask] = day_low.loc[mask]
            day_low.loc[mask] = temp_high.loc[mask]
            factors[product] = (day_high - day_low) / day_high
        return pd.DataFrame(factors)
    
    def func2(self, products: Sequence[Product], data_freq: Any = '1min',
             PCH: str = 'HA', PCL: str = 'LA') -> pd.DataFrame:
        factors = {}
        for product in products:
            df = product.get_data(data_freq)
            trading_day = df.index.get_level_values('trading_day').to_series().reset_index(drop=True)
            trade_time = df.index.get_level_values('trade_time').to_series().reset_index(drop=True)
            time_part = trade_time.dt.time
            cond = (time_part >= pd.Timestamp('09:00').time()) & (time_part <= pd.Timestamp('15:00').time())
            end_session = trading_day + pd.Timedelta('9 hours')
            end_session[cond] = trading_day[cond] + pd.Timedelta('15 hours')
            df.index = pd.MultiIndex.from_arrays([trading_day, end_session], names=['trading_day', 'end_session'])
            df_grouped = df.groupby(['trading_day', 'end_session'])

            day_high = df_grouped[PriceColumnMapping[PCH]].max()
            day_low = df_grouped[PriceColumnMapping[PCL]].min()
            idx_high = df_grouped[PriceColumnMapping[PCH]].idxmax()
            idx_low = df_grouped[PriceColumnMapping[PCL]].idxmin()
            mask = idx_low < idx_high
            temp_high = day_high.copy()
            day_high.loc[mask] = day_low.loc[mask]
            day_low.loc[mask] = temp_high.loc[mask]
            factors[product] = (day_high - day_low) / day_high
        return pd.DataFrame(factors)

if __name__ == '__main__':
    ff = DayMm()
    ff.add_params(PCH='H', PCL='L')
    ff.test(categories=['农产品'])