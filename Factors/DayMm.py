import numpy as np
import pandas as pd
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Products import ProductBase
from FactorTester import FactorGrid, PriceColumnMapping
from typing import List, Dict, Any

class DayMm(FactorGrid): # Day Momentum

    params_space: Dict[str, List[Any]] = {
        'PCH': ['HA', 'H'],
        'PCL': ['LA', 'L'],
        # 'W': [100, 150, 200],
    }

    default_params: Dict[str, Any] = {'PCH': 'HA', 'PCL': 'LA'}

    def _factor_func(self, data: Dict[ProductBase, pd.DataFrame], data_freq: Dict[ProductBase, pd.Timedelta],
                     PCH: str = 'HA', PCL: str = 'LA') -> pd.DataFrame:
        assert all(data_freq[product] < pd.Timedelta('1 day') for product in data_freq)
        assert len({v for v in data_freq.values()}) == 1
        factors = {}
        for product, df in data.items():
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

if __name__ == '__main__':
    DayMm().factor_grid_test(category_names=['农产品'])