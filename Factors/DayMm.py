import numpy as np
import pandas as pd
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Products import ProductBase
from FactorTester import FactorFamily, PriceColumnMapping
from typing import List, Dict, Any, Sequence, Tuple

class DayMm(FactorFamily): # Day Momentum

    params_space: Dict[str, List[Any]] = {
        'PCH': ['HA', 'H'],
        'PCL': ['LA', 'L'],
    }

    def func(self, products: Sequence[ProductBase], data_freq: Any = '1min',
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

if __name__ == '__main__':
    ff = DayMm()
    ff.add_params(PCH='H', PCL='L')
    ff.test(category_names=['贵金属'])