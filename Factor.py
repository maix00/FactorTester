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
from Parameter import Parameter, FinRangeParam, get_return_freq_param, get_start_calc_param, get_factor_freq_param
from CNFutures import get_all_futures  # TODO: Verify this function exists in CNFutures module
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

def get_factor_tester(time_range: Optional[Any] = None) -> FactorTester:
    products = get_all_futures()
    tester = FactorTester(products=products, time_range=time_range)
    return tester

class FactorFreqType(Enum):
    CONSTANT = 0
    AT_EVENT = 1

ReturnFreqParam = get_return_freq_param(alias='$RF')
StartCalcParam = get_start_calc_param(alias='$SC')
FactorFreqParam = get_factor_freq_param(alias='F')

class Factor(SerialObject):
    _instance_count: int = -1

    def __new__(cls, alias: Optional[str] = None, *args, **kwargs):
        instance = super().__new__(cls, type_alias='F', alias=alias, search=True)
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
    math_expr: str = ""
    _serial_map = {}
    params: List[Parameter] = []

    def __new__(cls, alias: Optional[str] = None, *args, **kwargs):
        alias=alias if alias else cls.__name__
        return super().__new__(cls, type_alias='FF', alias=alias)

    def __init__(self, alias: Optional[str] = None):
        if not hasattr(self, '_initialized'):
            alias=alias if alias else self.__class__.__name__
            super().__init__(type_alias='FF', alias=alias)
            self.params.append(FactorFreqParam)
            self.params_dict = {param.alias: param for param in self.params}
            self.set_default_params()
            self.current_start_calc_time: Any = None
            self.factors: List[Factor] = []

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

    def del_params(self, **kwargs):
        self._check_in_space(**kwargs)
        del_params = {p.alias: p.rectify_value(kwargs[p.alias]) if p.alias in kwargs else p.default_value for p in self.params}
        self._params_list = [params for params in self._params_list if params != del_params]

    def set_all_params(self):
        all_combinations = list(itertools.product(*[p.value_space if isinstance(p, FinRangeParam) else [p.default_value] for p in self.params]))
        self._params_list = [dict(zip([p.alias for p in self.params], combination)) for combination in all_combinations]

    def get_alias(self, **params):
        params_str = '|'.join(f"{key}:{self.params_dict[key].get_value_alias(value)}" for key, value in params.items())
        return f"{self.alias}|{params_str}" if params_str else self.alias

    def set_current_start_calc_time(self, start_cal_time: Optional[Any] = None):
        self.current_start_calc_time = start_cal_time

    def get_factors(self, return_freq: Optional[Any] = None, 
                    start_calc_time: Optional[Any] = None, **kwargs) -> List[Factor]:
        factors = []
        for params in self._params_list:
            factor_alias = self.get_alias(**params)
            factor_func = partial(self.func, **params)
            factor = Factor(alias=factor_alias, func=factor_func, family=self)
            for param_alias, value in params.items():
                self.params_dict[param_alias].register(factor, value)
            if return_freq is not None:
                factor.change_current_return_freq(return_freq)
            if start_calc_time is not None:
                factor.change_current_start_calc_time(start_calc_time)
            factors.append(factor)
        self.factors = factors
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

class FactorTester(SerialObject):
    _instances = WeakValueDictionary()

    def __new__(cls, alias: Optional[str] = None, *args, **kwargs):
        alias=alias if alias else cls.__name__
        return super().__new__(cls, type_alias='FT', alias=alias)
    
    def __init__(self, products: Sequence[Product],
                 alias: Optional[str] = None,
                 time_range: Optional[Tuple] = None,
                 logger_file: bool = True, logger_dir_path: str = logger_dir_path_default,
                 logger_console: bool = False):
        
        if not hasattr(self, '_initialized'):
            super().__init__(type_alias='FT', alias=alias)

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
                    logger_file_path = os.path.join(logger_dir_path, f"factor_tester_{self.serial_number}_{datetime.now().strftime('%Y%m%d')}.log")
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
    