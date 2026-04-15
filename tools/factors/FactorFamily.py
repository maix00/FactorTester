import os
import pandas as pd
from functools import partial
from weakref import WeakValueDictionary
from typing import TYPE_CHECKING, List, Optional, Sequence, Any, Tuple, Callable

from tqdm import tqdm

from tools.factors.Factor import Factor
from tools.products.Product import Product
from tools.factors.FactorTester import FactorTester, get_factor_tester
from tools import SerialObject, DataFreq, DataMeta, DataColumn
from tools.parameters.Parameter import Parameter, TimeDeltaParam, DataColumnParam, TypeParam
from tools.factors.Parameters import StartCalcPointParam, FactorFreqParam, FactorNextPeriodReturns

from Settings import sift_volume_ratio, default_plot_test_end_date, default_plot_test_start_date, default_test_end_date, default_test_start_date, factor_info_path

class FactorFamily(SerialObject):
    _instances = WeakValueDictionary()
    math_expr: str = ""
    _serial_map = {}
    params: List[Parameter] = []

    def __new__(cls, alias: Optional[str] = None, *args, **kwargs):
        alias=alias if alias else cls.__name__
        return super().__new__(cls, type_alias='FF', alias=alias)

    def __init__(self, alias: Optional[str] = None, factor_single_use: bool = False):
        if not hasattr(self, '_initialized'):
            alias=alias if alias else self.__class__.__name__
            super().__init__(type_alias='FF', alias=alias)
            self.params.append(FactorFreqParam)
            self.params_dict = {param.alias: param for param in self.params}
            self.set_default_params()
            self.factors: List[Factor] = []
            self.common_signal_freq: DataFreq
            self.factor_single_use = factor_single_use
            self.current_factor_tester: Optional['FactorTester'] = None
            self.current_sync_signal_index: Optional[pd.Index] = None

    def func(self, products: Sequence[Product], *args, **kwargs) -> pd.DataFrame:
        try:
            factors = {}
            signal_freq = kwargs.pop('F')
            if len(products) <= 200:
                for product in tqdm(products, desc=f"Calculating factor signals"):
                    factors[product] = self.sync_signal(self.func_timeseries(product, *args, **kwargs), signal_freq)
            else:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                def compute_factor(product, signal_freq, *args, **kwargs):
                    return product, self.sync_signal(self.func_timeseries(product, *args, **kwargs), signal_freq)
                with ThreadPoolExecutor(max_workers=8) as executor:
                    futures = {executor.submit(compute_factor, product, signal_freq, *args, **kwargs): product for product in products}
                    for future in tqdm(as_completed(futures), total=len(products), desc="Calculating factor signals"):
                        product, factor = future.result()
                        factors[product] = factor
            return pd.concat(factors, axis=1)
        except Exception as e:
            raise e
    
    def func_timeseries(self, product: Product, *args, **kwargs) -> Any:
        raise NotImplementedError("请在子类中实现 `func_timeseries` 方法")
    
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
        # all_combinations = list(itertools.product(*[p.value_space if isinstance(p, FinRangeParam) else [p.default_value] for p in self.params]))
        # self._params_list = [dict(zip([p.alias for p in self.params], combination)) for combination in all_combinations]
        return NotImplementedError("请在子类中实现 `set_all_params` 方法")

    def get_alias(self, **params):
        params_str = '|'.join(f"{key}:{self.params_dict[key].get_value_alias(value)}" for key, value in params.items())
        return f"{self.alias}|{params_str}" if params_str else self.alias

    def set_current_start_calc_point(self, start_calc_point: Optional[Any] = None):
        StartCalcPointParam.register(self, start_calc_point)

    def get_current_start_calc_point(self) -> Any:
        return StartCalcPointParam.get_value(self)
    
    if TYPE_CHECKING:
        from tools.parameters.Parameter import DateOrTimeParam
        
    def get_StartCalcPointParam(self) -> DateOrTimeParam:
        return StartCalcPointParam

    def get_factors(self, return_freq: Optional[Any] = None, 
                    start_calc_point: Optional[Any] = None, **kwargs) -> List[Factor]:
        factors = []
        for params in self._params_list:
            factor_alias = self.get_alias(**params)
            factor_func = partial(self.func, **params)
            factor = Factor(alias=factor_alias, func=factor_func, family=self, single_use=self.factor_single_use)
            for param_alias, value in params.items():
                self.params_dict[param_alias].register(factor, value)
            if return_freq is not None:
                factor.change_current_return_freq(return_freq)
            if start_calc_point is not None:
                factor.change_current_start_calc_point(start_calc_point, **kwargs)
            factors.append(factor)
        self.factors = factors
        return factors
    
    def get_factor(self, return_freq: Optional[Any] = None, start_calc_point: Optional[Any] = None, **kwargs):
        self._check_in_space(**kwargs)
        param_vals = {p: p.rectify_value(kwargs[p.alias]) if p.alias in kwargs else p.default_value for p in self.params}
        new_params = {p.alias: param_vals[p] for p in self.params}
        factor_alias = self.get_alias(**new_params)
        factor_func = partial(self.func, **new_params)
        factor = Factor(alias=factor_alias, func=factor_func, param_vals=param_vals, family=self, single_use=self.factor_single_use)
        if return_freq is not None:
            factor.change_current_return_freq(return_freq)
        if start_calc_point is not None:
            factor.change_current_start_calc_point(start_calc_point, **kwargs)
        return factor
    
    def test(self, categories: Optional[str|List[str]] = None,
             return_freq: Optional[Any] = None, 
             start_calc_point: Optional[Any] = None,
             ic_test_time_range: Optional[Tuple] = None,
             sift_volume_ratio: float = sift_volume_ratio, **kwargs) -> FactorTester:
        
        factor_cache_path = os.path.join(factor_info_path, self.alias, self.alias + '.csv')
        if not os.path.exists(factor_info_path):
            os.makedirs(factor_info_path)
        if os.path.exists(factor_cache_path) and os.path.isfile(factor_cache_path):
            factor_table = pd.read_csv(factor_cache_path)
        else:
            factor_table = pd.DataFrame()

        start_date = ic_test_time_range[0] if ic_test_time_range is not None else default_test_start_date
        end_date = ic_test_time_range[1] if ic_test_time_range is not None else default_test_end_date
        tester = get_factor_tester(time_range=(start_date, end_date))
        self.current_factor_tester = tester
        
        # tester.sift_product_by_category(categories=categories)
        returns_col = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED

        factors = self.get_factors(return_freq=return_freq, start_calc_point=start_calc_point, **kwargs)
        tester.calc_factor(factors)
        tester.calc_ic(returns_col=returns_col)
        
        for factor in factors:
            
            _, _, report_df = tester.test_by_group(factor, returns_col=returns_col,
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
    
    def _get_sync_signal_index(self, freq: Any, end_session_skip: bool = True, 
                    end_session_gap: pd.Timedelta = pd.Timedelta('3hours'),
                    day_basepoint: str|Callable = 'last', # 'last', 'first', '09:01:00'
                    **kwargs) -> pd.Index:
        if self.current_factor_tester is not None:
            products = self.current_factor_tester.products
        else:
            raise ValueError("No current factor tester is set on this Factor instance - cannot sync signal without a FactorTester to pull products from.")
        data_dict = {product: product.get_some_data() for product in products}
        first_trade_time = {product: data_dict[product].index.get_level_values(-1).min() for product in products}
        min_first_trade_time = min(first_trade_time.values())
        products_with_min_first_trade_time = [p for p, t in first_trade_time.items() if t == min_first_trade_time]
        assert bool(products_with_min_first_trade_time), "无法确定最早的交易时间，因为没有产品具有交易数据"
        data_length = {p: len(data_dict[p]) for p in products}
        max_data_length = max(data_length.values())
        product = next(p for p, l in data_length.items() if l == max_data_length)
        data = data_dict[product]
        del data_dict

        index_name_stem: str = '_SIGNAL'
        assert freq is not None, "Frequency must be provided"
        freq = DataFreq(freq)
        index_data_freq = [DataFreq(level) for level in data.index.names]
        
        index_map_of_multiple = [freq.value.total_seconds() % idx_freq.value.total_seconds() == 0 for idx_freq in index_data_freq]
        first_true_idx = next((i for i, is_multiple in enumerate(index_map_of_multiple) if is_multiple), None)
        assert first_true_idx is not None, f"Frequency {freq} is not a multiple of any existing index frequency"
        first_true_freq = index_data_freq[first_true_idx]
        multiple = int(freq.value.total_seconds() / first_true_freq.value.total_seconds())
        
        first_true_series = data.index.get_level_values(str(data.index.names[first_true_idx])).to_series().reset_index(drop=True)
        
        if isinstance(day_basepoint, str):
            day_basepoint = day_basepoint.lower()
            if day_basepoint == 'last':
                series = data.groupby(str(data.index.names[first_true_idx])).cumcount(ascending=False) == 0
            elif day_basepoint == 'first':
                series = data.groupby(str(data.index.names[first_true_idx])).cumcount() == 0
            else:
                try:
                    base_time = pd.Timestamp(day_basepoint).time()
                    series = data.groupby(str(data.index.names[first_true_idx])).transform(lambda x: pd.DatetimeIndex(x.index.get_level_values(-1)).time == base_time)
                except:
                    raise ValueError("Invalid day_basepoint value. Must be 'last', 'first', or a valid time string like '09:01:00'")
        else:
            series = day_basepoint(data.groupby(str(data.index.names[first_true_idx])))
        
        if not any(series):
            # If no True values are found, we can default to using the last position of each group as the base point
            series = data.groupby(str(data.index.names[first_true_idx])).cumcount(ascending=False) == 0

        assert isinstance(series, pd.Series) and series.dtype == bool, "day_basepoint function must return a boolean Series"
        first_true_change_pos = series.reset_index(drop=True).index[series]

        if end_session_skip and freq.value < pd.Timedelta('1day'):
            last_col_series = data.index.get_level_values(str(data.index.names[-1])).to_series().reset_index(drop=True)
            end_session_pos = last_col_series[last_col_series.shift(-1) - last_col_series >= end_session_gap].index
            signal_map_within_first_true_change_mask = first_true_change_pos.isin({i for start, end in zip([0] + (end_session_pos[:-1].values + 1).tolist(), end_session_pos) for i in range(start + multiple - 1, end + 1, multiple) if start + multiple - 1 <= end})
        else:
            index = first_true_change_pos.to_series().reset_index(drop=True).index
            signal_map_within_first_true_change_mask = (index % multiple == multiple - 1)

        signal_pos_within_first_true_series = first_true_change_pos[signal_map_within_first_true_change_mask]
        signal_map_within_first_true_series = first_true_series.index.isin(signal_pos_within_first_true_series)
        signal_series_within_first_true_series = first_true_series.where(signal_map_within_first_true_series)
        
        left_indices = data.index.names[:first_true_idx]
        right_indices = data.index.names[first_true_idx+1:]
        left_series_dict = {idx: data.index.get_level_values(str(idx)).to_series().where(signal_map_within_first_true_series) for idx in left_indices}
        right_series_dict = {idx: data.index.get_level_values(str(idx)).to_series() for idx in right_indices}
        index_arrays = [left_series_dict[idx] for idx in left_indices] \
                        + [signal_series_within_first_true_series] \
                        + [right_series_dict[idx] for idx in right_indices]
        index_names = [str(idx).split('@')[-1] for idx in left_indices] \
                    + [index_name_stem + '@' + freq.name] \
                    + [str(idx).split('@')[-1] for idx in right_indices]
        self.current_sync_signal_index = pd.MultiIndex.from_arrays(index_arrays, names=index_names).dropna()
        return self.current_sync_signal_index
    
    def sync_signal(self, data: Any, freq: Any, **kwargs) -> pd.DataFrame|pd.Series:
        if self.current_sync_signal_index is None:
            self._get_sync_signal_index(freq, **kwargs)
        assert self.current_sync_signal_index is not None
        if isinstance(data, DataMeta):
            data = data.data
        data = data[data.index.isin(self.current_sync_signal_index)]
        data.index.names = self.current_sync_signal_index.names
        return data
    
class Returns(FactorFamily):

    params = [
        TimeDeltaParam('RF', flag='pos', default_value='1d'), # Return Frequency, e.g. '1d', '1h', '30min', etc.
        DataColumnParam('SC', default_value=DataColumn.CLOSE), # Start Column for return calculation, e.g. DataColumn.CLOSE, DataColumn.OPEN, etc.
        DataColumnParam('EC', default_value=DataColumn.CLOSE), # End Column for return calculation, e.g. DataColumn.CLOSE, DataColumn.OPEN, etc.
        TypeParam('S', default_value=1), # Shift for return calculation, e.g. 1 for next return, 0 for current return, -1 for previous return, etc.
    ]

    def func_timeseries(self, product: Product, RF: pd.Timedelta, SC: DataColumn, EC: DataColumn, S: int, *args, **kwargs) -> pd.Series:
        data_freq = product.get_current_freq()
        data = getattr(product, data_freq.name)
        assert isinstance(data, DataMeta)
        if DataFreq(RF).is_day_multiple():
            multiple = int(RF / pd.Timedelta('1d'))
        else:
            multiple = int(RF / data_freq.value)
        if SC == EC:
            day_basepoint = 'last'
            if SC == DataColumn.OPEN or SC == DataColumn.OPEN_ADJUSTED:
                day_basepoint = 'first'
                ret = data[SC].pct_change(RF, day_basepoint=day_basepoint).shift(-multiple+S)
            elif SC == DataColumn.CLOSE or SC == DataColumn.CLOSE_ADJUSTED:
                ret = data[SC].pct_change(RF, day_basepoint=day_basepoint).shift(-multiple+S)
            else:
                raise ValueError("不支持的价格列，请选择 OPEN、OPEN_ADJUSTED、CLOSE 或 CLOSE_ADJUSTED")
            return data.sync_signal(ret, RF, day_basepoint='last', replace=True)
        else:
            start = data[SC].rolling(RF).first()
            end = data[EC].rolling(RF).last()
            ret = end / start - 1
            return data.sync_signal(ret, RF)

ReturnsFamily = Returns(factor_single_use=True)