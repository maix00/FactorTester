from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import itertools
from functools import partial
from weakref import WeakValueDictionary
import pandas as pd
import numpy as np
from typing import Callable, List, Dict, Optional, Sequence, Set, Tuple, Any, Literal
import os

from Tools import SerialObject
from Products import DataColumn, Futures, Product, DataFreq
from Parameter import Parameter, FinRangeParam, get_return_freq_param, get_start_calc_param
from CNFutures import get_all_products  # TODO: Verify this function exists in CNFutures module
import logging

from tqdm import tqdm

sift_volume_ratio = 0.8
default_test_start_date = '2025-01-01'
default_test_end_date = '2025-05-31'
default_plot_test_start_date = '2025-01-01'
default_plot_test_end_date = '2025-12-31'
logger_dir_path_default = '../data/factor_tester_log/'
factor_info_path = '../data/Factors/'

@dataclass
class ReturnType:
    return_freq: Optional[Any]
    start_type: Literal['first', 'last']
    start_col: DataColumn
    end_type: Literal['first', 'last']
    end_col: DataColumn

if __name__ == '__main__':
    ri = ReturnType('1d', 'first', DataColumn.OPEN, 'last', DataColumn.CLOSE)
    print(ri)

class ReturnPriceCols(Enum):
    NEXT_OPEN_TO_OPEN = (('first', DataColumn.OPEN), ('first', DataColumn.OPEN))
    NEXT_OPEN_TO_OPEN_ADJUSTED = (('first', DataColumn.OPEN_ADJUSTED), ('first', DataColumn.OPEN_ADJUSTED))
    THIS_CLOSE_TO_CLOSE = (('last', DataColumn.CLOSE), ('last', DataColumn.CLOSE))
    THIS_CLOSE_TO_CLOSE_ADJUSTED = (('last', DataColumn.CLOSE_ADJUSTED), ('last', DataColumn.CLOSE_ADJUSTED))

import inspect
import sys
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QPushButton, QComboBox, QFileDialog, QTextEdit
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading
import os
import webbrowser
import json
import calendar
from datetime import datetime

def get_factor_tester(time_range: Optional[Any] = None) -> FactorTester:
    products = get_all_products()
    tester = FactorTester(products=products, time_range=time_range)
    return tester

class FactorFreqType(Enum):
    CONSTANT = 0
    AT_EVENT = 1

ReturnFreqParam = get_return_freq_param(alias='$RF')
StartCalcParam = get_start_calc_param(alias='$SC')

class Factor(SerialObject):
    _instance_count: int = -1
    _serial_map = {}

    def __new__(cls, alias: Optional[str] = None, *args, **kwargs):
        instance = super().__new__(cls, type_alias='F', alias=alias)
        return instance
    
    def __init__(self, alias: Optional[str], func: Callable[..., pd.DataFrame], 
                 family: Optional[FactorFamily], param_vals: Optional[Dict[Parameter, Any]] = None):
        if not hasattr(self, '_initialized'):
            super().__init__(type_alias='F', alias=alias)
            self.func = func
            self.min_gap: Optional[pd.Timedelta] = None
            self.freq: Optional[pd.Timedelta] = None
            self.freq_type: FactorFreqType = FactorFreqType.AT_EVENT
            self.family = family
            
            if self.family is not None:
                assert param_vals is None
                self.params = self.family.params
            else:
                param_vals = param_vals if param_vals is not None else {}
                self.params = list(param_vals.keys()) if param_vals is not None else []
                for param in self.params:
                    param.register(self, param_vals[param])
            self.params_dict = {param.alias: param for param in self.params}

            self.table: pd.DataFrame = pd.DataFrame()
            self.products: Set[Product] = set()
            self.returns: pd.DataFrame = pd.DataFrame()
            self.ic_series: pd.Series = pd.Series()
            self.ic_stats: pd.Series = pd.Series()
            self.report: pd.DataFrame = pd.DataFrame()

    def get_current_return_freq(self) -> Any:
        return ReturnFreqParam.get_value(self)
    
    def change_current_return_freq(self, return_freq: Any) -> None:
        ReturnFreqParam.change_value(self, return_freq)

    def get_current_start_calc_time(self) -> Any:
        return StartCalcParam.get_value(self)
    
    def change_current_start_calc_time(self, start_calc_time: Any) -> None:
        StartCalcParam.change_value(self, start_calc_time)

    def _set_products(self) -> Set[Product]:
        if not self.table.empty:
            assert all(isinstance(col, Product) for col in self.table.columns)
            self.products = set([col for col in self.table.columns if isinstance(col, Product)])
        return self.products
    
    def _set_time_index(self):
        if self.table.empty:
            return
        if isinstance(self.table.index, pd.RangeIndex):
            time_cols = []
            for col in self.table.columns:
                if pd.api.types.is_datetime64_any_dtype(self.table[col]) or \
                    (self.table[col].dtype == 'object' and pd.to_datetime(self.table[col], errors='coerce').notna().any()):
                    time_cols.append(col)
            if not time_cols:
                raise ValueError("Cannot calculate frequency without time columns.")
            else:
                # Convert to datetime if needed
                for col in time_cols:
                    if not pd.api.types.is_datetime64_any_dtype(self.table[col]):
                        self.table[col] = pd.to_datetime(self.table[col], errors='coerce')
                # Sort time columns by precision (fewer non-zero time components = less precise = left side)
                def get_time_precision(col):
                    ls_comp = ['year', 'month', 'day', 'hour', 'minute', 'second', 'microsecond', 'nanosecond']
                    series = self.table[col]
                    comp = (any(getattr(series.dt, c) != 0) for c in ls_comp)
                    diffs = series.drop_duplicates().diff().dropna()
                    minimum = diffs.min()
                    mode = diffs.mode()[0]
                    if mode == minimum:
                        comp = list(comp) + [True, -mode]
                    else:
                        comp = list(comp) + [False, -minimum]
                    return comp
                time_cols_sorted = sorted(time_cols, key=lambda col: get_time_precision(col))
                # Set as index
                self.table.set_index(time_cols_sorted, inplace=True)

    def _calc_freq(self) -> Tuple[FactorFreqType, Any]:
        if self.table.empty:
            raise ValueError("Cannot calculate frequency without table.")
        if not self.products:
            self._set_products()
        if not self.products:
            raise ValueError("Cannot calculate frequency without products.")
        if not isinstance(self.table.index, pd.MultiIndex):
            series = self.table.index.to_series()
        else:
            idx_lvls = len(self.table.index.names)
            series = self.table.index.get_level_values(idx_lvls-1).to_series()
        series = pd.to_datetime(series, errors='coerce').sort_values()
        assert series.notna().all(), "Unable to convert all values to datetime"
        diffs = series.diff().dropna()
        minimum = diffs.min()
        self.min_gap = minimum
        day_dividable = all(diff.total_seconds() % pd.Timedelta('1 day').total_seconds() == 0 for diff in diffs)
        end_of_day = all(ts.hour == 0 and ts.minute == 0 and ts.second == 0 for ts in series.dropna())
        if day_dividable and end_of_day:
            return FactorFreqType.AT_EVENT, pd.Timedelta('1day')
        end_of_session = True
        for i in range(min(20, len(series))):
            end = all(not product.if_time_is_in_data(list(series)[i] + product.get_current_freq().value) for product in self.products) 
            start = all(not product.if_time_is_in_data(list(series)[i] - product.get_current_freq().value) for product in self.products)
            if not (end or start):
                end_of_session = False
                break
        if day_dividable or end_of_day or end_of_session:
            return FactorFreqType.AT_EVENT, None
        mode = diffs.mode()[0]
        if mode != minimum:
            return FactorFreqType.AT_EVENT, None
        return FactorFreqType.CONSTANT, minimum

    def calc(self, products: Any) -> pd.DataFrame:
        if isinstance(products, Product):
            products = [products]
        products = list(products)
        if self.family is not None:
            start_calc_time = self.get_current_start_calc_time()
            self.family.set_current_start_calc_time(start_calc_time)
        self.table = self.func(products).reset_index()
        self._set_time_index()
        for col in self.table.columns:
            if max(self.table[col].dropna()) == min(self.table[col].dropna()):
                self.table.drop(columns=col, inplace=True)
        self._set_products()
        self.freq_type, self.freq = self._calc_freq()
        return self.table
    
    def calc_returns(self, next_return: bool = True,
                     price_cols: ReturnPriceCols = ReturnPriceCols.NEXT_OPEN_TO_OPEN) -> pd.DataFrame:
        returns = {}
        return_freq = self.get_current_return_freq()
        changeable_return_freq = return_freq is None and self.freq is None
        return_freq = return_freq or self.freq
        if not changeable_return_freq:
            assert return_freq is not None
            return_freq = pd.Timedelta(return_freq)
            assert return_freq <= (self.freq if self.freq is not None else \
                self.min_gap if self.min_gap is not None else return_freq)
        if changeable_return_freq:
            price_cols = ReturnPriceCols.NEXT_OPEN_TO_OPEN
        for product in self.table.columns:
            assert isinstance(product, Product)
            PC = price_cols
            if isinstance(product, Futures):
                if price_cols == ReturnPriceCols.NEXT_OPEN_TO_OPEN:
                    PC = ReturnPriceCols.NEXT_OPEN_TO_OPEN_ADJUSTED
                elif price_cols == ReturnPriceCols.THIS_CLOSE_TO_CLOSE:
                    PC = ReturnPriceCols.THIS_CLOSE_TO_CLOSE_ADJUSTED
            assert self.min_gap is not None
            all_f = product.list_available_freqs()
            assert len(all_f) > 0
            data_freq = sorted([_f for _f in all_f if _f.value <= self.min_gap \
                                and self.min_gap.total_seconds() % _f.value.total_seconds() == 0
                                and (return_freq.total_seconds() % _f.value.total_seconds() == 0 
                                    if return_freq is not None else True)
                                and (self.freq.total_seconds() % _f.value.total_seconds() == 0 
                                    if self.freq is not None else True)], 
                                key=lambda x: x.value)[-1]
            # data_freq = DataFreq.MIN1
            if not changeable_return_freq:
                assert return_freq is not None
                assert return_freq.total_seconds() % data_freq.value.total_seconds() == 0, f"return_freq必须是数据频率{data_freq}的整数倍，现在为{return_freq}"
            df = getattr(product, data_freq.name).get_and_adjust_cols([col.name for _, col in PC.value])
            notna_index = self.table.index[self.table[product].notna()]
            target_series = pd.Series(index=notna_index, dtype=float)
            if not changeable_return_freq:
                assert return_freq is not None
                time_cols = product.get_time_cols(data_freq)
                index_time_col = [col for col in time_cols if
                    self.min_gap.total_seconds() % DataFreq[col].value.total_seconds() == 0
                    and (self.freq.total_seconds() % DataFreq[col].value.total_seconds() == 0 
                        if self.freq is not None else True)]
                index_time_col = sorted(index_time_col, key=lambda x: DataFreq[str(x)].value)[-1]
                pos = df.index.get_level_values(index_time_col).searchsorted(
                    notna_index.get_level_values(notna_index.nlevels-1), 
                    side='right'
                )
                pos = pos - 1 if PC.value[0][0] == 'last' else pos
                period = int(return_freq.total_seconds() / data_freq.value.total_seconds())
                pos_end = pos + period
                valid = (pos_end < len(df.index)) & (pos >= 0) & (np.concatenate((pos[:-1] != pos[1:], [False])))
                if valid.any():
                    indecies = notna_index[valid]
                    start_indecies = df.index[pos[valid]]
                    end_indecies = df.index[pos_end[valid]]
                    start_series = df.loc[start_indecies, PC.value[0][1].name].reset_index(drop=True)
                    end_series = df.loc[end_indecies, PC.value[1][1].name].reset_index(drop=True)
                    return_series = (end_series - start_series) / start_series
                    return_series = return_series if next_return else return_series.shift(1)
                    target_series.loc[indecies] = return_series.values
            else:
                assert PC.value[0][0] == 'first'
                pos = df.index.searchsorted(notna_index, side='right')
                valid = (pos < len(df.index)) & (np.concatenate((pos[:-1] != pos[1:], [False])))
                if valid.any():
                    target_col = PC.value[0][1].name
                    indecies = notna_index[valid]
                    start_indecies = df.index[pos[valid]]
                    start_series = df.loc[start_indecies, target_col]
                    offset = -1 if next_return else 0
                    return_series = start_series.pct_change(periods=1).shift(offset)
                    target_series.loc[indecies] = return_series.values
            returns[product] = target_series
        self.returns = pd.DataFrame(returns)
        return self.returns

class FactorFamily(SerialObject):
    _instances = WeakValueDictionary()
    _instance_count: int = -1
    _serial_map = {}
    params: List[Parameter] = []

    def __new__(cls, alias: Optional[str] = None, *args, **kwargs):
        alias=alias if alias else cls.__name__
        return super().__new__(cls, type_alias='FF', alias=alias)

    def __init__(self, alias: Optional[str] = None):
        if not hasattr(self, '_initialized'):
            alias=alias if alias else self.__class__.__name__
            super().__init__(type_alias='FF', alias=alias)
            self.params_dict = {param.alias: param for param in self.params}
            self.set_default_params()
            self.current_start_calc_time: Any = None

    def func(self, products: Sequence[Product], *args, **kwargs) -> pd.DataFrame:
        raise NotImplementedError("请在子类中实现 `factor_func` 方法")
    
    def set_default_params(self):
        self._params_list = [{p.alias: p.default_value for p in self.params}]

    def change_param_default_value(self, **kwargs):
        self._check_in_space(**kwargs)
        for key, value in kwargs.items():
            self.params_dict[key].default_value = value

    def clear_params(self):
        self._params_list = []
    
    def _check_in_space(self, **kwargs):
        for key in kwargs:
            if not self.params_dict[key].check_in_space(kwargs[key]):
                raise ValueError
            
    def add_params(self, **kwargs):
        self._check_in_space(**kwargs)
        new_params = {p.alias: p.rectify_value(kwargs[p.alias]) if p.alias in kwargs else p.default_value for p in self.params}
        if new_params not in self._params_list:
            self._params_list.append(new_params)

    def set_all_params(self):
        all_combinations = list(itertools.product(*[p.value_space if isinstance(p, FinRangeParam) else [p.default_value] for p in self.params]))
        self._params_list = [dict(zip([p.alias for p in self.params], combination)) for combination in all_combinations]

    def get_alias(self, **params):
        params_str = '|'.join(f"{key}:{self.params_dict[key].get_value_alias(value)}" for key, value in params.items())
        return f"{self.alias}|{params_str}" if params_str else self.alias

    def set_current_start_calc_time(self, start_cal_time: Optional[Any] = None):
        self.current_start_calc_time = start_cal_time

    def get_factors(self, return_freq: Optional[Any] = None, 
                    start_cal_time: Optional[Any] = None, **kwargs) -> List[Factor]:
        factors = []
        for params in self._params_list:
            factor_alias = self.get_alias(**params)
            factor_func = partial(self.func, **params)
            factor = Factor(alias=factor_alias, func=factor_func, family=self)
            for param_alias, value in params.items():
                self.params_dict[param_alias].register(factor, value)
            if return_freq is not None:
                factor.change_current_return_freq(return_freq)
            if start_cal_time is not None:
                factor.change_current_start_calc_time(start_cal_time)
            factors.append(factor)
        return factors
    
    def get_factor(self, return_freq: Optional[Any] = None, start_cal_time: Optional[Any] = None, **kwargs):
        self._check_in_space(**kwargs)
        new_params = {p.alias: p.rectify_value(kwargs[p.alias]) if p.alias in kwargs else p.default_value for p in self.params}
        factor_alias = self.get_alias(**new_params)
        factor_func = partial(self.func, **new_params)
        factor = Factor(alias=factor_alias, func=factor_func, params=new_params, family=self)
        if return_freq is not None:
            factor.change_current_return_freq(return_freq)
        if start_cal_time is not None:
            factor.change_current_start_calc_time(start_cal_time)
        return factor
    
    def test(self, categories: Optional[str|List[str]] = None,
             return_freq: Optional[Any] = None, 
             start_cal_time: Optional[Any] = None,
             sift_volume_ratio: float = sift_volume_ratio, **kwargs) -> FactorTester:
        
        factor_cache_path = os.path.join(factor_info_path, self.alias, self.alias + '.csv')
        if not os.path.exists(factor_info_path):
            os.makedirs(factor_info_path)
        if os.path.exists(factor_cache_path) and os.path.isfile(factor_cache_path):
            factor_table = pd.read_csv(factor_cache_path)
        else:
            factor_table = pd.DataFrame()
        
        tester = get_factor_tester(time_range=(default_test_start_date, default_test_end_date))

        # from FactorTesterGUI import set_objects, start_gui
        # set_objects(self, tester)
        # start_gui(threaded=False, debug=True)
        
        tester.sift_product_by_category(categories=categories)
        price_cols = ReturnPriceCols.NEXT_OPEN_TO_OPEN

        factors = self.get_factors(return_freq=return_freq, start_cal_time=start_cal_time, **kwargs)
        tester.calc_factor(factors)
        tester.calc_ic(return_price_cols=price_cols)
        
        for factor in factors:
            
            _, _, report_df = tester.test_by_group(factor, return_price_cols=price_cols,
                plot_flag=True, time_range=(default_plot_test_start_date, default_plot_test_end_date),
                plot_show=False, plot_remark_str=','.join(categories) if categories else None, **kwargs
                )
            
            report_dict = {}
            for col in report_df.columns:
                key_0 = f"{col} {report_df.index[0]}"
                report_dict[key_0] = report_df.loc[report_df.index[0], col]
            for col in report_df.columns:
                key_1 = f"{col} {report_df.index[1]}"
                report_dict[key_1] = report_df.loc[report_df.index[1], col]

            new_row = pd.Series({
                'factor_stem': self.alias,
                'serial_num': pd.Timestamp.now(),
                'factor_name': factor.alias,
                'factor_freq': factor.freq,
                'start_date': tester.start_date,
                'end_date': tester.end_date,
                'sift_volume_ratio': sift_volume_ratio,
                'categories': categories,
            } | factor.params_dict | factor.ic_stats.to_dict() | report_dict)
            factor_table = pd.concat([factor_table, new_row.to_frame().T], ignore_index=True)
            factor.report = factor_table
            factor_table.to_csv(factor_cache_path, index=False)

        return tester

class FactorTester:
    def __init__(self, products: Sequence[Product],
                 time_range: Optional[Tuple] = None,
                 logger_file: bool = True, logger_dir_path: str = logger_dir_path_default,
                 logger_console: bool = False):
        
        self.logger = logging.getLogger(self.__class__.__name__)
        if not self.logger.handlers:

            self.logger.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

            if logger_console:
                console_handler = logging.StreamHandler()
                console_handler.setFormatter(formatter)
                self.logger.addHandler(console_handler)

            if logger_file:
                if not os.path.exists(logger_dir_path):
                    os.makedirs(logger_dir_path)
                logger_file_path = os.path.join(logger_dir_path, "factor_tester_{}.log".format(datetime.now().strftime("%Y%m%d")))
                file_handler = logging.FileHandler(logger_file_path, encoding='utf-8')
                file_handler.setFormatter(formatter)
                self.logger.addHandler(file_handler)
        
        self.products = set(products)
        self.all_products = set(products)
        self.sift_product_by_empty_data_bool = False
        self.factors = []
        self.start_date = pd.to_datetime(time_range[0]) if time_range is not None else None
        self.end_date = pd.to_datetime(time_range[1]) if time_range is not None else None
        self.logger.info(f"FactorTester initialized with {len(self.products)} products")
    
    def sift_product(self, sift_func: Callable[[Product], bool]):
        new_products = set()
        for product in self.products:
            if sift_func(product):
                new_products.add(product)
        self.products = new_products

    def sift_product_by_category(self, categories: Optional[str|List[str]] = None):
        if categories is None:
            return
        if isinstance(categories, str):
            categories = [categories]
        new_products = set()
        for product in self.products:
            for category in categories:
                if product.get_category() == category:
                    new_products.add(product)
                    break
        self.products = new_products

    def sift_product_by_empty_data(self):
        new_products = set()
        for product in self.products:
            df = product.get_some_data(copy=False)
            if not df.empty and max(df[DataColumn.VOLUME.name]) > 0:
                new_products.add(product)
        self.products = new_products
        self.sift_product_by_empty_data_bool = True

    def sift_product_by_volumes(self, ratio: Optional[float] = None, time_col: Optional[Any] = None,
                                time_range: Optional[Any] = None) -> Set[Product]:
        if ratio is None:
            return self.products
        if not self.sift_product_by_empty_data_bool:
            self.sift_product_by_empty_data()
        results = {}
        for product in self.products:
            sum_volume = product.get_slices(target_cols=DataColumn.VOLUME, 
                                                  time_col=time_col, time_range=time_range,
                                                  copy=False).sum().values
            if sum_volume == 0:
                continue
            results[product] = sum_volume
        sorted_products = sorted(results, key=lambda x: results[x], reverse=True)
        return set(sorted_products[:int(len(sorted_products) * ratio)])
        
    def calc_factor(self, factors: Factor|List[Factor]):
        if isinstance(factors, Factor):
            factors = [factors]
        self.factors = factors
        self.sift_product_by_empty_data()
        for factor in tqdm(factors, desc='Calculate for factors'):
            factor.calc(self.products)
    
    def calc_rank(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.loc[:, df.columns.isin(self.products)]
        return df.rank(axis=1, method='average', na_option='keep', pct=True)
    
    def calc_ic(self, return_price_cols: ReturnPriceCols = ReturnPriceCols.NEXT_OPEN_TO_OPEN,
                factors: Optional[Factor|List[Factor]] = None,
                time_range: Optional[Tuple] = None,) -> tuple[pd.DataFrame, pd.DataFrame]:
                        
        factors = [factors] if isinstance(factors, Factor) else \
            (factors if factors is not None else self.factors)
        start_date = pd.to_datetime(time_range[0]) if time_range is not None else self.start_date
        end_date = pd.to_datetime(time_range[1]) if time_range is not None else self.end_date
        
        ic_series = {}
        ic_stats = {}

        for factor in tqdm(factors, desc='Calculating IC'):
            factor_rank = self.calc_rank(factor.table)
            return_df = factor.calc_returns(next_return=True, price_cols=return_price_cols) if factor.returns.empty else factor.returns
            assert not return_df.empty
            return_rank = self.calc_rank(return_df)
            dt_index = factor_rank.index.intersection(return_rank.index)
            if start_date is not None:
                dt_index = dt_index[[start_date <= (max(k) if not isinstance(k, pd.Timestamp) else k) for k in dt_index]]
            if end_date is not None:
                dt_index = dt_index[[(min(k) if not isinstance(k, pd.Timestamp) else k) <= end_date for k in dt_index]]
            ic = []
            coverage = []
            for dt in dt_index:
                f = factor_rank.loc[dt]
                r = return_rank.loc[dt]
                valid = f.notna() & r.notna()
                coverage.append(valid.sum())
                if valid.sum() > 1:
                    ic.append(pd.Series(f[valid]).corr(r[valid], method='spearman'))
                else:
                    ic.append(np.nan)
            factor.ic_series = pd.Series(ic, index=dt_index)
            ic_series[factor.alias] = factor.ic_series
            avg_coverage = np.mean(coverage)
            stats_df = self.ic_stats(ic_series[factor.alias])
            stats_df['avg_coverage'] = avg_coverage
            factor.ic_stats = stats_df
            ic_stats[factor.alias] = stats_df
        return pd.DataFrame(ic_series), pd.DataFrame(ic_stats)

    def ic_stats(self, ic_series: pd.Series) -> pd.Series:
        mean = ic_series.mean()
        std = ic_series.std()
        ir = mean / std if std != 0 else np.nan
        t_stat = mean / (std / np.sqrt(len(ic_series.dropna()))) if std != 0 and len(ic_series.dropna()) > 1 else np.nan
        max_ic = ic_series.max()
        min_ic = ic_series.min()
        stats_df = pd.Series({
            'mean': mean, 'std': std, 'IR': ir, 't_stat': t_stat, 'max': max_ic, 'min': min_ic
        })
        return stats_df

    def test_by_group(self, factors: Optional[Factor|List[Factor]] = None,
                      return_price_cols: ReturnPriceCols = ReturnPriceCols.NEXT_OPEN_TO_OPEN,
                      n_groups: int = 5, n_groups_name: Dict[int, str] = {},
                      time_range: Optional[Tuple] = None,
                      plot_remark_str: Optional[str] = None,
                      plot_flag: bool = False, save_plot: bool = True, plot_show: bool = True,
                      plot_n_group_list: Optional[List[int]] = None,
                      sift_volume_ratio: Optional[float] = None) -> Tuple[Any, Any, pd.DataFrame]:

        factors = [factors] if isinstance(factors, Factor) else \
            (factors if factors is not None else self.factors)

        if plot_flag and plot_n_group_list is not None:
            plot_n_group_list = [n_groups + n_group if n_group < 0 else n_group for n_group in plot_n_group_list] if plot_n_group_list else None

        products = {i: {} for i in range(n_groups)}
        returns = {i: {} for i in range(n_groups)}
        names = {i: n_groups_name.get(i, 'group_' + str(i)) for i in range(n_groups)}

        start_date = pd.to_datetime(time_range[0]) if time_range is not None else self.start_date
        end_date = pd.to_datetime(time_range[1]) if time_range is not None else self.end_date
        
        report_df = pd.DataFrame()
        for factor in factors:

            if factor.returns.empty:
                factor.calc_returns(next_return=True, price_cols=return_price_cols)
            assert not factor.returns.empty

            last_dt, _ = next(factor.table.iterrows())
            for dt, row in tqdm(factor.table.iterrows(), desc='Testing by group for factor ' + factor.alias):
                sifted_products = self.products
                # sifted_products = self.sift_product_by_volumes(
                #     ratio=sift_volume_ratio, 
                #     time_range=(last_dt if dt != last_dt else None, dt)
                # )
                sorted_products = sorted(row.dropna().index, key=lambda x: (row[x], x.name), reverse=True)
                sorted_products = [product for product in sorted_products if product in sifted_products]
                n = len(sorted_products)
                idx = list(sorted_products)
                
                # Split contracts into n_groups groups
                if n == 0:
                    continue
                else:
                    n_split = n_groups
                    last_dt_has_product_now_at_market = set(range(n_groups))
                    for i in range(n_groups):
                        if not products[i]:
                            products[i][dt] = []
                        else:
                            # products[i][dt] = []
                            products[i][dt] = [product for product in products[i][last_dt]
                                if np.isnan(factor.returns[product].loc[dt])]
                            if products[i][dt] and len(products[i][dt]) == len(products[i][last_dt]):
                                last_dt_has_product_now_at_market.remove(i)
                            n_split = len(last_dt_has_product_now_at_market)
                    bucket_idx = np.floor(np.linspace(0, n_split, len(idx), endpoint=False)).astype(int)
                    split = [list(np.asarray(idx)[bucket_idx == i]) for i in range(n_split)]
                    last_dt_has_product_now_at_market = sorted(list(last_dt_has_product_now_at_market))
                    for i, group in enumerate(split):
                        products[last_dt_has_product_now_at_market[i]][dt].extend(group)

                for i in range(n_groups):
                    series = factor.returns[products[i][dt]].loc[dt].fillna(0)
                    returns[i][dt] = 0 if series.empty else np.mean(series.values)

                last_dt, _ = dt, row

            report_groups = {}
            for idx in range(n_groups):

                dates = list(returns[idx].keys()) if returns[idx] else []
                test_dates = [date for date in dates if self.start_date <= (max(date) if not isinstance(date, pd.Timestamp) else date)] if self.start_date else dates
                test_dates = [date for date in test_dates if (min(date) if not isinstance(date, pd.Timestamp) else date) <= self.end_date] if self.end_date else dates
                dates = [date for date in dates if start_date <= (max(date) if not isinstance(date, pd.Timestamp) else date)] if start_date else dates
                dates = [date for date in dates if (min(date) if not isinstance(date, pd.Timestamp) else date) <= end_date] if end_date else dates
                
                returns_list = [returns[idx][date] for date in dates]
                returns_series = pd.Series(returns_list).dropna()
                cumulative_returns = (1 + returns_series).cumprod()

                test_returns = [returns[idx][date] for date in test_dates]
                test_returns_series = pd.Series(test_returns).dropna()
                test_cumulative_returns = (1 + test_returns_series).cumprod()

                metrics = {

                '(Test) Total Return': (test_cumulative_returns.iloc[-1] - 1) * 100 if len(test_cumulative_returns) > 0 else 0,
                '(Test) Annual Return': ((test_cumulative_returns.iloc[-1]) ** (252 / len(test_cumulative_returns)) - 1) * 100 if len(test_cumulative_returns) > 1 else 0,
                '(Test) Volatility': pd.Series(test_returns).std() * np.sqrt(252) * 100,
                '(Test) Sharpe Ratio': (pd.Series(test_returns).mean() * 252) / (pd.Series(test_returns).std() * np.sqrt(252)) if pd.Series(test_returns).std() != 0 else 0,
                '(Test) Max Drawdown': ((test_cumulative_returns.cummax() - test_cumulative_returns) / test_cumulative_returns.cummax()).max() * 100 if len(test_cumulative_returns) > 0 else 0,
                '(Test) Calmar Ratio': ((test_cumulative_returns.iloc[-1] ** (252 / len(test_cumulative_returns)) - 1) * 100) / (((test_cumulative_returns.cummax() - test_cumulative_returns) / test_cumulative_returns.cummax()).max() * 100) if ((test_cumulative_returns.cummax() - test_cumulative_returns) / test_cumulative_returns.cummax()).max() != 0 else 0,
                '(Test) Win Rate': (pd.Series(test_returns) > 0).sum() / len(pd.Series(test_returns)) * 100 if len(pd.Series(test_returns)) > 0 else 0,
                '(Test) Mean Return': pd.Series(test_returns).mean() * 100,
                '(Test) Skewness': pd.Series(test_returns).skew(),
                '(Test) Kurtosis': pd.Series(test_returns).kurtosis(),

                'Total Return': (cumulative_returns.iloc[-1] - 1) * 100 if len(cumulative_returns) > 0 else 0,
                'Annual Return': ((cumulative_returns.iloc[-1]) ** (252 / len(cumulative_returns)) - 1) * 100 if len(cumulative_returns) > 1 else 0,
                'Volatility': pd.Series(returns_list).std() * np.sqrt(252) * 100,
                'Sharpe Ratio': (pd.Series(returns_list).mean() * 252) / (pd.Series(returns_list).std() * np.sqrt(252)) if pd.Series(returns_list).std() != 0 else 0,
                'Max Drawdown': ((cumulative_returns.cummax() - cumulative_returns) / cumulative_returns.cummax()).max() * 100 if len(cumulative_returns) > 0 else 0,
                'Calmar Ratio': ((cumulative_returns.iloc[-1] ** (252 / len(cumulative_returns)) - 1) * 100) / (((cumulative_returns.cummax() - cumulative_returns) / cumulative_returns.cummax()).max() * 100) if ((cumulative_returns.cummax() - cumulative_returns) / cumulative_returns.cummax()).max() != 0 else 0,
                'Win Rate': (pd.Series(returns_list) > 0).sum() / len(pd.Series(returns_list)) * 100 if len(pd.Series(returns_list)) > 0 else 0,
                'Mean Return': pd.Series(returns_list).mean() * 100,
                'Skewness': pd.Series(returns_list).skew(),
                'Kurtosis': pd.Series(returns_list).kurtosis(),

                }

                report_groups[idx] = pd.Series(metrics)
            
            report_df = pd.DataFrame(report_groups).T.sort_index()  # Convert to DataFrame, transpose, and sort by name
            if not plot_flag or (plot_flag and plot_show):
                with pd.option_context('display.max_rows', None, 'display.max_columns', None):
                    print("Group Performance Summary:\n", report_df)

            if plot_flag:
                import matplotlib.pyplot as plt
                # Plot average open returns per group over time
                plt.figure(figsize=(12, 6))
                start_date = start_date if start_date is not None else self.start_date
                end_date = end_date if end_date is not None else self.end_date
                # print(start_date, end_date)
                dates = []  # Initialize dates as an empty list
                for idx in range(n_groups):
                    if plot_n_group_list is not None and idx not in plot_n_group_list:
                        continue
                    dates = list(returns[idx].keys()) if returns[idx] else []
                    dates = [date for date in dates if start_date <= (max(date) if not isinstance(date, pd.Timestamp) else date)] if start_date else dates
                    dates = [date for date in dates if (min(date) if not isinstance(date, pd.Timestamp) else date) <= end_date] if end_date else dates
                    returns_list = [returns[idx][date] for date in dates]
                    cumulative_returns = []
                    prev_value = 10000
                    for ret in returns_list:
                        if not np.isnan(ret):
                            prev_value = prev_value * (1 + ret)
                        cumulative_returns.append(prev_value)
                    plt.plot([str(date[-1].date()) if isinstance(date, tuple) else str(date.date()) for date in dates], cumulative_returns, label=names[idx])
                plt.xlabel('日期')
                plt.ylabel('平均收益')
                if plot_remark_str:
                    plt.title(f'平均收益: {factor.alias} - {plot_remark_str}')
                else:
                    plt.title(f'平均收益: {factor.alias}')
                plt.rcParams['font.sans-serif'] = ['Kaiti SC']
                plt.legend()
                # Only show every nth tick to reduce crowding
                n_ticks = 10
                assert len(dates) > 0, "No dates available for plotting."
                tick_indices = np.linspace(0, len(dates) - 1, min(n_ticks, len(dates)), dtype=int)
                # plt.xticks(ticks=[str(dates[i][-1].date()) if isinstance(dates[i], tuple) else str(dates[i].date()) for i in tick_indices], rotation=45)
                ticks = [str(dates[i][-1].date()) if isinstance(dates[i], tuple) else str(dates[i].date()) for i in tick_indices]
                plt.xticks(ticks=ticks, rotation=45)
                plt.tight_layout()
                if save_plot:
                    factor_stem = factor.alias.split('|')[0]
                    figs_path = os.path.join(factor_info_path, factor_stem, 'figs')
                    if not os.path.exists(figs_path):
                        os.makedirs(figs_path)
                    plt.savefig(os.path.join(figs_path, f'{factor.alias}_{start_date}_{end_date}.png'))
                if plot_show:
                    plt.show()

        return products, returns, report_df
    

# factor_server.py

import importlib.util

from Settings import *

def get_factor_groups(factors_dir):
    factor_files = [f for f in os.listdir(factors_dir) if f.endswith(".py")]
    factor_names = [os.path.splitext(f)[0] for f in factor_files]

    def get_group(name):
        group = ""
        upper_count = 0
        for i, c in enumerate(name):
            if c.isupper():
                upper_count += 1
                if upper_count == 1:
                    group += c
                elif upper_count == 2:
                    break
            else:
                if upper_count == 1:
                    group += c
        return group if group else name

    groups = {}
    for name in factor_names:
        group = get_group(name)
        groups.setdefault(group, []).append(name)
    return groups, factor_names

def build_group_html(groups):
    group_html = ""
    for group, names in sorted(groups.items()):
        group_html += f'<div style="margin-bottom:16px;"><b style="font-size:20px;color:#0078d4;">{group}</b>'
        group_html += '<ul style="max-height:180px;overflow-y:auto;border:1px solid #eee;border-radius:4px;padding:0;margin-top:8px;">'
        for name in sorted(names):
            group_html += f'<li style="padding:8px;border-bottom:1px solid #eee;"><a href="?factor={name}" style="text-decoration:none;color:#333;font-size:18px;">{name}</a></li>'
        group_html += '</ul></div>'
    return group_html

class TimeRangeModule:
    html_id = "time_range_module"
    parent_id = None
    title = "1. 起始/终末时间设置"
    is_open = True

    @classmethod
    def html(cls):
        def pad(n):
            return f"{int(n):02d}"
        # 判断初始是否显示下一个模块
        start_dt = f"{default_test_start_date} {default_day_start_time}"
        end_dt = f"{default_test_end_date} {default_day_end_time}"
        show_next = ""
        try:
            sdt = datetime.strptime(start_dt, "%Y-%m-%d %H:%M")
            edt = datetime.strptime(end_dt, "%Y-%m-%d %H:%M")
            if sdt <= edt:
                show_next = f"openModule('{CategoryFilterModule.html_id}');"
            else:
                show_next = f"closeModule('{CategoryFilterModule.html_id}');"
        except Exception:
            show_next = f"closeModule('{CategoryFilterModule.html_id}');"
        return f"""
            <div class="module" id="{cls.html_id}" style="margin-top:32px;">
            <div class="section-title">{cls.title}</div>
            <div style="display:flex;align-items:center;gap:24px;">
                <span style="font-size:13px;">
                起始日期: 
                <input type="number" min="1900" max="2100" id="start_year" value="{default_test_start_date[:4]}" style="width:60px;background:#eee;border:none;border-radius:4px;font-size:16px;margin-left:8px;">
                <span style="font-size:16px;">-</span>
                <input type="number" min="1" max="12" id="start_month" value="{pad(default_test_start_date[5:7])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;">
                <span style="font-size:16px;">-</span>
                <input type="number" min="1" max="31" id="start_day" value="{pad(default_test_start_date[8:10])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;">
                </span>
                <span style="font-size:13px;">
                起始时间: 
                <input type="number" min="0" max="23" id="start_hour" value="{pad(default_day_start_time[:2])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;margin-left:8px;">
                <span style="font-size:16px;">:</span>
                <input type="number" min="0" max="59" id="start_minute" value="{pad(default_day_start_time[3:5])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;">
                </span>
            </div>
            <div style="display:flex;align-items:center;gap:24px;margin-top:12px;">
                <span style="font-size:13px;">
                终末日期: 
                <input type="number" min="1900" max="2100" id="end_year" value="{default_test_end_date[:4]}" style="width:60px;background:#eee;border:none;border-radius:4px;font-size:16px;margin-left:8px;">
                <span style="font-size:16px;">-</span>
                <input type="number" min="1" max="12" id="end_month" value="{pad(default_test_end_date[5:7])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;">
                <span style="font-size:16px;">-</span>
                <input type="number" min="1" max="31" id="end_day" value="{pad(default_test_end_date[8:10])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;">
                </span>
                <span style="font-size:13px;">
                终末时间: 
                <input type="number" min="0" max="23" id="end_hour" value="{pad(default_day_end_time[:2])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;margin-left:8px;">
                <span style="font-size:16px;">:</span>
                <input type="number" min="0" max="59" id="end_minute" value="{pad(default_day_end_time[3:5])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;">
                </span>
            </div>
            <div style="margin-top:16px;">
                <label style="font-size:13px;">
                <input type="checkbox" id="is_trading_day" style="width:16px;height:16px;vertical-align:middle;margin-right:8px;">
                <span style="font-size:13px;vertical-align:middle;">交易日</span>
                </label>
            </div>
            <div style="margin-top:5px;">
                <label style="font-size:13px;">
                <input type="checkbox" id="is_cn_futures_day" style="width:16px;height:16px;vertical-align:middle;margin-right:8px;">
                <span style="font-size:13px;vertical-align:middle;">中国期货日盘 (09:00-15:00)</span>
                </label>
                <label style="font-size:13px;margin-left:24px;">
                <input type="checkbox" id="is_cn_futures_night" style="width:16px;height:16px;vertical-align:middle;margin-right:8px;">
                <span style="font-size:13px;vertical-align:middle;">中国期货夜盘 (21:00-15:00)</span>
                </label>
            </div>
            <script>
                var default_cn_futures_day_start = "{default_cn_futures_day_start}";
                var default_cn_futures_day_end = "{default_cn_futures_day_end}";
                var default_cn_futures_night_start = "{default_cn_futures_night_start}";
                var default_cn_futures_night_end = "{default_cn_futures_night_end}";

                function toggleCnFuturesDayNight(event) {{
                    var target = event.target;
                    var dayCheckbox = document.getElementById('is_cn_futures_day');
                    var nightCheckbox = document.getElementById('is_cn_futures_night');
                    var tradingDayElem = document.getElementById('is_trading_day');

                    // 如果点击的是日盘，并且日盘被勾选，则强制取消夜盘
                    if (target === dayCheckbox && dayCheckbox.checked) {{
                        nightCheckbox.checked = false;
                    }}
                    // 如果点击的是夜盘，并且夜盘被勾选，则强制取消日盘
                    else if (target === nightCheckbox && nightCheckbox.checked) {{
                        dayCheckbox.checked = false;
                    }}
                    // 如果点击的是同一个复选框并取消勾选，则两个都未选中（允许都不选）
                    // 无需额外操作

                    // 更新交易日复选框状态（如果日盘或夜盘选中，则取消交易日）
                    if (dayCheckbox.checked || nightCheckbox.checked) {{
                        tradingDayElem.checked = false;
                    }}

                    // 重新获取当前状态
                    var is_day = dayCheckbox.checked;
                    var is_night = nightCheckbox.checked;

                    // 根据最终状态设置时间输入框
                    if (is_day && !is_night) {{
                        document.getElementById('start_hour').value = pad(parseInt(default_cn_futures_day_start.split(':')[0]));
                        document.getElementById('start_minute').value = pad(parseInt(default_cn_futures_day_start.split(':')[1]));
                        document.getElementById('end_hour').value = pad(parseInt(default_cn_futures_day_end.split(':')[0]));
                        document.getElementById('end_minute').value = pad(parseInt(default_cn_futures_day_end.split(':')[1]));
                        setTimeInputsDisabled(true);
                    }} else if (!is_day && is_night) {{
                        document.getElementById('start_hour').value = pad(parseInt(default_cn_futures_night_start.split(':')[0]));
                        document.getElementById('start_minute').value = pad(parseInt(default_cn_futures_night_start.split(':')[1]));
                        document.getElementById('end_hour').value = pad(parseInt(default_cn_futures_night_end.split(':')[0]));
                        document.getElementById('end_minute').value = pad(parseInt(default_cn_futures_night_end.split(':')[1]));
                        setTimeInputsDisabled(true);
                    }} else {{
                        // 两个都未选中时，恢复默认时间并可编辑
                        setTimeInputsDisabled(false);
                        document.getElementById('start_hour').value = pad(parseInt(default_day_start_time.split(':')[0]));
                        document.getElementById('start_minute').value = pad(parseInt(default_day_start_time.split(':')[1]));
                        document.getElementById('end_hour').value = pad(parseInt(default_day_end_time.split(':')[0]));
                        document.getElementById('end_minute').value = pad(parseInt(default_day_end_time.split(':')[1]));
                    }}

                    updateCurrentSettings();
                }}

                document.addEventListener('DOMContentLoaded', function() {{
                    document.getElementById('is_cn_futures_day').addEventListener('change', toggleCnFuturesDayNight);
                    document.getElementById('is_cn_futures_night').addEventListener('change', toggleCnFuturesDayNight);
                }});
            </script>
            <div style="margin-top:8px;color:#888;">
                <span>当前设置：</span>
                <span id="current_settings"></span>
            </div>
            <script>
                var default_start_date = "{default_test_start_date}";
                var default_end_date = "{default_test_end_date}";
                var default_day_start_time = "{default_day_start_time}";
                var default_day_end_time = "{default_day_end_time}";

                function pad(n) {{
                    n = parseInt(n);
                    return n < 10 ? '0' + n : n.toString();
                }}

                function getMaxDay(year, month) {{
                    year = parseInt(year);
                    month = parseInt(month);
                    if (isNaN(year) || isNaN(month) || month < 1 || month > 12) return 31;
                    return new Date(year, month, 0).getDate();
                }}

                function validateInputOnBlur(input, min, max, isDay, yearId, monthId) {{
                    var value = input.value;
                    if (value === "") {{
                        input.value = pad(min);
                    }} else {{
                        var num = parseInt(value);
                        if (isNaN(num)) {{
                            input.value = pad(min);
                        }} else if (num < min) {{
                            input.value = pad(min);
                        }} else if (num > max) {{
                            input.value = pad(max);
                        }} else {{
                            input.value = pad(num);
                        }}
                    }}
                    if (isDay) {{
                        var year = document.getElementById(yearId).value;
                        var month = document.getElementById(monthId).value;
                        var maxDay = getMaxDay(year, month);
                        if (parseInt(input.value) > maxDay) {{
                        input.value = pad(maxDay);
                        }}
                    }}
                    updateCurrentSettings();
                }}

                function validateInputOnEnter(e, input, min, max, isDay, yearId, monthId) {{
                    if (e.key === "Enter") {{
                        validateInputOnBlur(input, min, max, isDay, yearId, monthId);
                    }}
                }}

                function adjustDayIfNeeded(dayId, yearId, monthId) {{
                    var year = document.getElementById(yearId).value;
                    var month = document.getElementById(monthId).value;
                    var dayElem = document.getElementById(dayId);
                    var maxDay = getMaxDay(year, month);
                    var dayVal = parseInt(dayElem.value);
                    if (isNaN(dayVal) || dayVal < 1) {{
                        dayElem.value = pad(1);
                    }} else if (dayVal > maxDay) {{
                        dayElem.value = pad(maxDay);
                    }}
                }}

                function getStartEndDateTime() {{
                    var start_year = document.getElementById('start_year').value;
                    var start_month = pad(document.getElementById('start_month').value);
                    var start_day = pad(document.getElementById('start_day').value);
                    var start_hour = pad(document.getElementById('start_hour').value);
                    var start_minute = pad(document.getElementById('start_minute').value);

                    var end_year = document.getElementById('end_year').value;
                    var end_month = pad(document.getElementById('end_month').value);
                    var end_day = pad(document.getElementById('end_day').value);
                    var end_hour = pad(document.getElementById('end_hour').value);
                    var end_minute = pad(document.getElementById('end_minute').value);

                    var start_str = start_year + "-" + start_month + "-" + start_day + " " + start_hour + ":" + start_minute;
                    var end_str = end_year + "-" + end_month + "-" + end_day + " " + end_hour + ":" + end_minute;
                    return [start_str, end_str];
                }}

                function updateCurrentSettings() {{
                    var start_year = document.getElementById('start_year').value;
                    var start_month = pad(document.getElementById('start_month').value);
                    var start_day = pad(document.getElementById('start_day').value);
                    var start_hour = pad(document.getElementById('start_hour').value);
                    var start_minute = pad(document.getElementById('start_minute').value);

                    var end_year = document.getElementById('end_year').value;
                    var end_month = pad(document.getElementById('end_month').value);
                    var end_day = pad(document.getElementById('end_day').value);
                    var end_hour = pad(document.getElementById('end_hour').value);
                    var end_minute = pad(document.getElementById('end_minute').value);

                    var is_trading_day = document.getElementById('is_trading_day').checked;
                    var txt = "起始时间: " + start_year + "-" + start_month + "-" + start_day + " " + start_hour + ":" + start_minute 
                        + ", 终末时间: " + end_year + "-" + end_month + "-" + end_day + " " + end_hour + ":" + end_minute + (is_trading_day ? " (交易日)" : "");
                    document.getElementById('current_settings').innerText = txt;

                    // 判断起始时间是否小于等于终末时间，控制下一个模块显示
                    var start_str = start_year + "-" + start_month + "-" + start_day + " " + start_hour + ":" + start_minute;
                    var end_str = end_year + "-" + end_month + "-" + end_day + " " + end_hour + ":" + end_minute;
                    var start_dt = new Date(start_str.replace(/-/g, '/'));
                    var end_dt = new Date(end_str.replace(/-/g, '/'));
                    if (!isNaN(start_dt.getTime()) && !isNaN(end_dt.getTime()) && start_dt <= end_dt) {{
                        openModule('{CategoryFilterModule.html_id}');
                    }} else {{
                        closeModule('{CategoryFilterModule.html_id}');
                    }}
                }}

                function setTimeInputsDisabled(disabled) {{
                    var timeIds = ['start_hour', 'start_minute', 'end_hour', 'end_minute'];
                    timeIds.forEach(function(id) {{
                        var elem = document.getElementById(id);
                        elem.disabled = disabled;
                        elem.style.background = disabled ? '#ccc' : '#eee';
                        elem.style.color = disabled ? '#888' : '';
                    }});
                }}

                function toggleTradingDay() {{
                    var is_trading_day = document.getElementById('is_trading_day').checked;
                    // 选择交易日时，取消日盘和夜盘
                    if(is_trading_day) {{
                        document.getElementById('is_cn_futures_day').checked = false;
                        document.getElementById('is_cn_futures_night').checked = false;
                        document.getElementById('start_hour').value = "00";
                        document.getElementById('start_minute').value = "00";
                        document.getElementById('end_hour').value = "00";
                        document.getElementById('end_minute').value = "00";
                        setTimeInputsDisabled(true);
                    }} else {{
                        document.getElementById('start_hour').value = pad(parseInt(default_day_start_time.split(':')[0]));
                        document.getElementById('start_minute').value = pad(parseInt(default_day_start_time.split(':')[1]));
                        document.getElementById('end_hour').value = pad(parseInt(default_day_end_time.split(':')[0]));
                        document.getElementById('end_minute').value = pad(parseInt(default_day_end_time.split(':')[1]));
                        setTimeInputsDisabled(false);
                    }}
                    updateCurrentSettings();
                }}

                document.addEventListener('DOMContentLoaded', function() {{
                    document.getElementById('start_year').value = default_start_date.slice(0,4);
                    document.getElementById('start_month').value = pad(default_start_date.slice(5,7));
                    document.getElementById('start_day').value = pad(default_start_date.slice(8,10));
                    document.getElementById('start_hour').value = pad(parseInt(default_day_start_time.split(':')[0]));
                    document.getElementById('start_minute').value = pad(parseInt(default_day_start_time.split(':')[1]));
                    document.getElementById('end_year').value = default_end_date.slice(0,4);
                    document.getElementById('end_month').value = pad(default_end_date.slice(5,7));
                    document.getElementById('end_day').value = pad(default_end_date.slice(8,10));
                    document.getElementById('end_hour').value = pad(parseInt(default_day_end_time.split(':')[0]));
                    document.getElementById('end_minute').value = pad(parseInt(default_day_end_time.split(':')[1]));
                    document.getElementById('is_trading_day').addEventListener('change', toggleTradingDay);

                    var inputs = [
                        ['start_year', 1900, 2100, false, '', ''],
                        ['start_month', 1, 12, false, '', ''],
                        ['start_day', 1, 31, true, 'start_year', 'start_month'],
                        ['start_hour', 0, 23, false, '', ''],
                        ['start_minute', 0, 59, false, '', ''],
                        ['end_year', 1900, 2100, false, '', ''],
                        ['end_month', 1, 12, false, '', ''],
                        ['end_day', 1, 31, true, 'end_year', 'end_month'],
                        ['end_hour', 0, 23, false, '', ''],
                        ['end_minute', 0, 59, false, '', '']
                    ];
                    inputs.forEach(function(arr) {{
                        var id = arr[0], min = arr[1], max = arr[2], isDay = arr[3], yearId = arr[4], monthId = arr[5];
                        var elem = document.getElementById(id);
                        elem.addEventListener('blur', function() {{
                            validateInputOnBlur(elem, min, max, isDay, yearId, monthId);
                            if (id === 'start_year' || id === 'start_month') {{
                                adjustDayIfNeeded('start_day', 'start_year', 'start_month');
                            }}
                            if (id === 'end_year' || id === 'end_month') {{
                                adjustDayIfNeeded('end_day', 'end_year', 'end_month');
                            }}
                        }});
                        elem.addEventListener('keydown', function(e) {{
                            validateInputOnEnter(e, elem, min, max, isDay, yearId, monthId);
                            if (e.key === "Enter") {{
                                if (id === 'start_year' || id === 'start_month') {{
                                adjustDayIfNeeded('start_day', 'start_year', 'start_month');
                                }}
                                if (id === 'end_year' || id === 'end_month') {{
                                adjustDayIfNeeded('end_day', 'end_year', 'end_month');
                                }}
                            }}
                        }});
                        elem.addEventListener('input', function() {{
                            updateCurrentSettings();
                            if (id === 'start_year' || id === 'start_month') {{
                                adjustDayIfNeeded('start_day', 'start_year', 'start_month');
                            }}
                            if (id === 'end_year' || id === 'end_month') {{
                                adjustDayIfNeeded('end_day', 'end_year', 'end_month');
                            }}
                        }});
                    }});
                    toggleTradingDay();
                    updateCurrentSettings();
                    {show_next}
                }});
            </script>
            </div>
        """

class CategoryFilterModule:
    html_id = "category_filter_module"
    parent_id = TimeRangeModule.html_id
    title = "2. 产品类别筛选"
    is_open = False

    @classmethod
    def html(cls):
        return f"""
        <div class="module" id="{cls.html_id}" style="margin-top:32px;display:none;">
            <div class="section-title">{cls.title}</div>
            <div style="color:#aaa;">（功能开发中）</div>
        </div>
        """

class IcTestModule:
    html_id = "ic_test_module"
    parent_id = CategoryFilterModule.html_id
    title = "3. IC测试"
    is_open = False

    @classmethod
    def html(cls):
        return f"""
        <div class="module" id="{cls.html_id}" style="margin-top:32px;display:none;">
            <div class="section-title">{cls.title}</div>
            <button disabled style="background:#ccc;">运行IC测试</button>
            <div style="color:#aaa;">（功能开发中）</div>
        </div>
        """

class GroupTestModule:
    html_id = "group_test_module"
    parent_id = IcTestModule.html_id
    title = "4. 分组测试"
    is_open = False

    @classmethod
    def html(cls):
        return f"""
        <div class="module" id="{cls.html_id}" style="margin-top:32px;display:none;">
            <div class="section-title">{cls.title}</div>
            <button disabled style="background:#ccc;">运行分组测试</button>
            <div style="color:#aaa;">（功能开发中）</div>
        </div>
        """

def html_factor_main_section(selected_name):
    return f"""
        <div class="section">
            <div class="section-title">当前因子: <b style="color:#0078d4;">{selected_name}</b></div>
            <div style="margin-top:16px;color:#888;">功能开发中，仅展示页面框架。</div>
            {TimeRangeModule.html()}
            {CategoryFilterModule.html()}
            {IcTestModule.html()}
            {GroupTestModule.html()}
        </div>
        <script>
            // 控制模块显示/隐藏
            function openModule(moduleId) {{
                document.getElementById(moduleId).style.display = '';
            }}
            function closeModule(moduleId) {{
                document.getElementById(moduleId).style.display = 'none';
            }}
            function checkModules() {{
                // 只有父模块完成后才打开下一个模块
                var modules = [
                    '{TimeRangeModule.html_id}',
                    '{CategoryFilterModule.html_id}',
                    '{IcTestModule.html_id}',
                    '{GroupTestModule.html_id}'
                ];
                // 默认第一个模块打开
                openModule(modules[0]);
                for (var i = 1; i < modules.length; i++) {{
                    closeModule(modules[i]);
                }}
                // 你可以在这里加条件，比如父模块完成后再打开下一个模块
                // 这里只是演示，实际需要根据状态判断
                // 例如：如果时间设置完成，则打开类别筛选模块
                // 可以通过事件监听和状态管理实现
            }}
            document.addEventListener('DOMContentLoaded', checkModules);
        </script>
    """

class FactorFileHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        directory = self.directory
        factors_dir = os.path.join(directory, "Factors")
        if not os.path.exists(factors_dir):
            os.makedirs(factors_dir)
        groups, factor_names = get_factor_groups(factors_dir)

        search_query = ""
        if "search=" in self.path:
            search_query = self.path.split("search=")[-1].split("&")[0]
            factor_names_filtered = [name for name in factor_names if search_query.lower() in name.lower()]
            filtered_groups = {}
            for group, names in groups.items():
                filtered = [n for n in names if search_query.lower() in n.lower()]
                if filtered:
                    filtered_groups[group] = filtered
            groups = filtered_groups
        else:
            factor_names_filtered = factor_names

        selected_name = self.path.split("?factor=")[-1] if "?factor=" in self.path else ""
        group_html = build_group_html(groups)

        if selected_name and selected_name in factor_names:
            html_content = f"""
            <html>
            <head>
                <title>单因子测试</title>
                <style>
                    body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f6f8fa; }}
                    .container {{ display: flex; max-width: 1200px; margin: 40px auto; background: #fff; border-radius: 8px; box-shadow: 0 2px 8px #ddd; padding: 32px; position: relative; min-height: 700px; }}
                    .sidebar {{ width: 320px; border-right: 1px solid #eee; padding-right: 24px; }}
                    .main {{ flex: 1; padding-left: 32px; }}
                    h2 {{ color: #222; }}
                    input[type="text"] {{ width: 100%; padding: 8px; margin-bottom: 16px; border-radius: 4px; border: 1px solid #ccc; font-size: 16px; }}
                    ul {{ list-style: none; padding: 0; margin: 0; }}
                    li:hover {{ background: #e6f7ff; }}
                    button {{ margin-top: 24px; padding: 8px 16px; border-radius: 4px; border: none; background: #0078d4; color: #fff; font-size: 16px; cursor: pointer; }}
                    .group-title {{ font-size:20px;color:#0078d4;margin-bottom:8px; }}
                    .shutdown-btn-topright {{
                        position: absolute;
                        top: 16px;
                        right: 16px;
                        padding: 8px 16px;
                        border-radius: 4px;
                        border: none;
                        background: #d40000;
                        color: #fff;
                        font-size: 16px;
                        cursor: pointer;
                        z-index: 10;
                    }}
                    .section {{ margin-bottom: 32px; }}
                    .section-title {{ font-size:18px;color:#0078d4;margin-bottom:8px; }}
                    .module {{ border: 1px solid #eee; border-radius: 6px; background: #fafbfc; margin-bottom: 16px; padding: 16px; }}
                </style>
                <script>
                    function searchFactors() {{
                        var query = document.getElementById('search').value;
                        window.location.href = '?search=' + encodeURIComponent(query);
                    }}
                    function shutdownServer() {{
                        if (confirm('确定要关闭服务器吗？')) {{
                            fetch('/shutdown', {{method: 'POST'}}).then(function() {{
                                // 关闭页面
                                window.close();
                            }});
                        }}
                    }}
                    document.addEventListener('DOMContentLoaded', function() {{
                        document.getElementById('search').addEventListener('keyup', function(e) {{
                            if (e.key === 'Enter') searchFactors();
                        }});
                    }});
                </script>
            </head>
            <body>
                <button class="shutdown-btn-topright" onclick="shutdownServer()">关闭服务器</button>
                <div class="container">
                    <div class="sidebar">
                        <h2>单因子测试 (./Factors)</h2>
                        <input type="text" id="search" placeholder="搜索因子名称..." value="{search_query}">
                        {group_html if groups else '<div style="color:#888;">无匹配因子</div>'}
                        <button onclick="shutdownServer()">关闭服务器</button>
                    </div>
                    <div class="main">
                        {html_factor_main_section(selected_name)}
                    </div>
                </div>
            </body>
            </html>
            """
        else:
            html_content = f"""
            <html>
            <head>
                <title>单因子测试</title>
                <style>
                    body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f6f8fa; }}
                    .container {{ max-width: 700px; margin: 40px auto; background: #fff; border-radius: 8px; box-shadow: 0 2px 8px #ddd; padding: 32px; position: relative; }}
                    h2 {{ color: #222; }}
                    input[type="text"] {{ width: 100%; padding: 8px; margin-bottom: 16px; border-radius: 4px; border: 1px solid #ccc; font-size: 16px; }}
                    ul {{ list-style: none; padding: 0; margin: 0; }}
                    li:hover {{ background: #e6f7ff; }}
                    button {{ margin-top: 24px; padding: 8px 16px; border-radius: 4px; border: none; background: #0078d4; color: #fff; font-size: 16px; cursor: pointer; }}
                    .group-title {{ font-size:20px;color:#0078d4;margin-bottom:8px; }}
                    .shutdown-btn-topright {{
                        position: absolute;
                        top: 16px;
                        right: 16px;
                        padding: 8px 16px;
                        border-radius: 4px;
                        border: none;
                        background: #d40000;
                        color: #fff;
                        font-size: 16px;
                        cursor: pointer;
                        z-index: 10;
                    }}
                </style>
                <script>
                    function searchFactors() {{
                        var query = document.getElementById('search').value;
                        window.location.href = '?search=' + encodeURIComponent(query);
                    }}
                    function shutdownServer() {{
                        if (confirm('确定要关闭服务器吗？')) {{
                            fetch('/shutdown', {{method: 'POST'}}).then(function() {{
                                // 关闭页面
                                window.close();
                            }});
                        }}
                    }}
                    document.addEventListener('DOMContentLoaded', function() {{
                        document.getElementById('search').addEventListener('keyup', function(e) {{
                            if (e.key === 'Enter') searchFactors();
                        }});
                    }});
                </script>
            </head>
            <body>
                <div class="container">
                    <button class="shutdown-btn-topright" onclick="shutdownServer()">关闭服务器</button>
                    <h2>单因子测试 (./Factors)</h2>
                    <input type="text" id="search" placeholder="搜索因子名称..." value="{search_query}">
                    {group_html if groups else '<div style="color:#888;">无匹配因子</div>'}
                    <button onclick="shutdownServer()">关闭服务器</button>
                </div>
            </body>
            </html>
            """

        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html_content.encode("utf-8"))

    def do_POST(self):
        if self.path == '/shutdown':
            self.send_response(200)
            self.end_headers()
            threading.Thread(target=self.server.shutdown).start()
            sys.exit(0)
        else:
            self.send_response(404)
            self.end_headers()

def run_local_http_server(port=8000, directory='.'):
    os.chdir(directory)
    class CustomHTTPServer(HTTPServer):
        def __init__(self, server_address, RequestHandlerClass, directory):
            super().__init__(server_address, RequestHandlerClass)
            self.directory = directory

    server = CustomHTTPServer(('localhost', port), FactorFileHandler, directory)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://localhost:{port}/"
    print(f"Serving HTTP on {url} from {os.path.abspath(directory)}")
    webbrowser.open(url)
    thread.join()
    print("服务器已关闭。")

if __name__ == '__main__':
    run_local_http_server(port=8000, directory='.')
