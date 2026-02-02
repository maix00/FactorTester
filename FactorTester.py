from datetime import datetime
from enum import Enum
import itertools
import pandas as pd
import numpy as np
from typing import Callable, List, Dict, Optional, Set, Tuple, Any
import os

from Products import Futures, ProductBase
import logging

from tqdm import tqdm

logger_dir_path_default = '../data/factor_tester_log/'
factor_info_path = '../data/Factors/'

PriceColumnMapping = {
    'C': 'close_price',
    'O': 'open_price',
    'H': 'highest_price',
    'L': 'lowest_price',
    'CA': 'close_price_adjusted',
    'OA': 'open_price_adjusted',
    'HA': 'highest_price_adjusted',
    'LA': 'lowest_price_adjusted',
    'V': 'vwap',
    'T': 'twap',
}

OtherColumnMapping = {
    'V': 'volume',
    'A': 'amount',
    'T': 'turnover',
    'P': 'premium',
    'D': 'dividend',
    'R': 'right',
    'E': 'exchange_rate',
    'S': 'spread',
    'M': 'mid_price',
    'I': 'implied_volatility',
    'B': 'bid_price',
    'A': 'ask_price',
    'BW': 'bid_width',
    'AW': 'ask_width',
    'BW/A': 'bid_ask_width_ratio',
    'B/A': 'bid_ask_ratio',
    'B/A/M': 'bid_ask_mid_ratio'
}

import inspect

class FactorGrid:
    # 子类需覆盖：参数的可选范围
    params_space: Dict[str, List[Any]] = {}
    # 子类需覆盖：默认参数
    default_params: Dict[str, Any] = {}

    def __init__(self, factor_name_stem: Optional[str] = None):
        self.factor_name_stem = factor_name_stem if factor_name_stem else self.__class__.__name__
        self.current_params_space = self.params_space

    def _factor_func(self, data: Dict[ProductBase, pd.DataFrame], 
                     data_freq: Dict[ProductBase, pd.Timedelta], *args, **kwargs) -> pd.DataFrame:
        raise NotImplementedError("请在子类中实现 `factor_func` 方法。")
    
    def _set_current_params_space(self, **kwargs):
        if not kwargs:
            return
        for key in kwargs:
            if not isinstance(kwargs[key], list):
                kwargs[key] = [kwargs[key]]
        self.current_params_space = self._get_complete_params(**{**self.params_space, **kwargs})

    def _get_complete_params(self, **kwargs) -> Dict[str, Any]:
        """合并默认参数并校验合法性"""
        # 1. 以默认值为基础，用传入的 kwargs 覆盖
        full_params = {**self.default_params, **kwargs}
        
        # 2. 校验参数是否在定义的范围内
        for k, v in full_params.items():
            if k in self.params_space:
                if not isinstance(v, list):
                    v = [v]
                if not all(vv in self.params_space[k] for vv in v):
                    raise ValueError(f"参数 '{k}' 的值 '{v}' 不在允许范围 {self.params_space[k]} 内")
            else:
                # 如果传入了 params_space 没定义的参数，可以报错或警告
                raise KeyError(f"未定义的参数名: '{k}'")
        
        # 3. 排序以保证 get_factor_name 的一致性
        return dict(sorted(full_params.items()))

    def get_factor_func(self, **kwargs) -> Callable[[Dict[ProductBase, pd.DataFrame], Dict[ProductBase, pd.Timedelta]], pd.DataFrame]:
        params = self._get_complete_params(**kwargs)
        return lambda data, data_freq: self._factor_func(data, data_freq, **params)

    def get_factor_name(self, **kwargs) -> str:
        params = self._get_complete_params(**kwargs)
        kwargs_str = '|'.join(f"{k}:{v}" for k, v in params.items())
        parts = [self.factor_name_stem, kwargs_str]
        return '|'.join(p for p in parts if p)

    def get_factor(self, **kwargs) -> tuple[str, Callable[[Dict[ProductBase, pd.DataFrame], Dict[ProductBase, pd.Timedelta]], pd.DataFrame]]:
        return self.get_factor_name(**kwargs), self.get_factor_func(**kwargs)
    
    def get_factor_list(self, **kwargs) -> List[tuple[str, Callable]]:
        return self.get_factor_tensor(**kwargs).flatten().tolist()
    
    def get_factor_name_list(self, **kwargs) -> List[str]:
        return [name for name, func in self.get_factor_list(**kwargs)]
    
    def get_param_tensor_shape(self, **kwargs) -> tuple[int, ...]:
        self._set_current_params_space(**kwargs)
        return tuple(len(v) for v in self.current_params_space.values())

    def get_param_tensor(self, **kwargs) -> np.ndarray:
        """
        生成多维张量，每个维度对应一个参数，值为参数取值列表
        """
        self._set_current_params_space(**kwargs)
        keys = list(self.current_params_space.keys())
        values = list(self.current_params_space.values())
        
        # 获取每个参数的取值数量
        shape = tuple(len(v) for v in values)
        
        # 创建对象数组来存储参数取值列表
        tensor = np.empty(shape, dtype=object)
        
        # 填充张量
        for combination in itertools.product(*values):
            # 根据combination获取索引
            indices = tuple(values[i].index(combination[i]) for i in range(len(keys)))
            tensor[indices] = combination
        
        return tensor
    
    def get_factor_tensor(self, **kwargs) -> np.ndarray:
        """
        生成多维张量，每个维度对应一个参数，值为(因子名, 因子函数)的元组
        """
        self._set_current_params_space(**kwargs)
        keys = list(self.current_params_space.keys())
        values = list(self.current_params_space.values())
        
        # 获取每个参数的取值数量
        shape = tuple(len(v) for v in values)
        
        # 创建对象数组来存储元组
        tensor = np.empty(shape, dtype=object)
        
        # 填充张量
        for combination in itertools.product(*values):
            spec_kwargs = dict(zip(keys, combination))
            factor_name, factor_func = self.get_factor(**spec_kwargs)
            
            # 根据combination获取索引
            indices = tuple(values[i].index(combination[i]) for i in range(len(keys)))
            tensor[indices] = (factor_name, factor_func)
        
        return tensor
    
    def factor_test(self, n_groups: int = 5, plot_n_group_list: Optional[List[int]] = None, **kwargs):
        params = self._get_complete_params(**kwargs)
        factor_test(self.get_factor(**params), n_groups=n_groups, plot_n_group_list=plot_n_group_list)

    # def factor_grid_test(self, **kwargs):
    #     self._set_current_params_space(**kwargs)
    #     factor_test(self)

    def factor_grid_test(self, n_groups: int = 5, plot_n_group_list: Optional[List[int]] = None, **kwargs):
        
        factor_cache_path = os.path.join(factor_info_path, self.factor_name_stem + '.csv')
        if not os.path.exists(factor_info_path):
            os.makedirs(factor_info_path)
        if os.path.exists(factor_cache_path) and os.path.isfile(factor_cache_path):
            factor_table = pd.read_csv(factor_cache_path)
        else:
            factor_table = pd.DataFrame()
        
        tester = get_factor_tester()
        
        all_values = self.get_param_tensor(**kwargs).flatten().tolist()
        all_keys = self.params_space.keys()
        for values in all_values:
            params = dict(zip(all_keys, values))
            factor = self.get_factor(**params)
            factor_name = factor[0]

            tester.calc_factor(factor)
            _, ic_stats = tester.calc_ic(factor, return_price_col='open_price_adjusted',
                                         return_daily_anchors='open_market')
            
            _, _, report_df = tester.group_classes(factor_name, 
                plot_flag=True, n_groups=n_groups, plot_n_group_list=plot_n_group_list,
                start_date='2025-01-01', end_date='2025-12-31',
                return_price_col='open_price_adjusted', return_daily_anchors='open_market'
                )
            
            report_dict = {}
            for col in report_df.columns:
                key_0 = f"{col} {report_df.index[0]}"
                report_dict[key_0] = report_df.loc[report_df.index[0], col]
            for col in report_df.columns:
                key_1 = f"{col} {report_df.index[1]}"
                report_dict[key_1] = report_df.loc[report_df.index[1], col]

            new_row = pd.Series({
                'factor_stem': self.factor_name_stem,
                'serial_num': pd.Timestamp.now(),
                'factor_name': factor_name,
            } | params | ic_stats.iloc[:, 0].to_dict() | report_dict)
            factor_table = pd.concat([factor_table, new_row.to_frame().T], ignore_index=True)
            factor_table.to_csv(factor_cache_path, index=False)
        
class FactorTester:
    def __init__(self, file_paths: List[str], 
                 start_date: Optional[str] = None, end_date: Optional[str] = None,
                 time_col: str|List[str] = ['trading_day', 'trade_time'],
                 futures_flag: bool = True, futures_adjust_col: Optional[List[str]] = None,
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
        
        self.set_time_col(time_col)
        self.products = []
        self.data = {}
        self.data_freq = {}
        self.factor_data = {}
        self.factor_freq = {}
        self.product_mapping = {}
        self.return_data = {}
        for path in file_paths:
            product_name = path.split('/')[-1].replace('.parquet', '')
            product = Futures(product_name) if futures_flag else ProductBase(product_name)
            self.add_data(product, path, futures_adjust_col=futures_adjust_col)
        self.start_date = start_date
        self.end_date = end_date
        self.futures_flag = futures_flag
        self.futures_adjust_col = futures_adjust_col
        self.logger.info(f"FactorTester initialized with {len(self.products)} products")

    def set_time_col(self, time_col: str|List[str]):
        self.time_col = time_col
        self.time_col_num = 0
        if isinstance(time_col, str):
            self.time_col = [time_col]
        if len(self.time_col) == 1:
            self.time_col_num = 1
            self.logger.info(f"将`time_col`设置为单列: {self.time_col[0]}")
        elif len(self.time_col) == 2:
            self.time_col_num = 2
            self.logger.info(f"将`time_col`设置为双列: {self.time_col[0]} and {self.time_col[1]}")
            self.logger.info("首列假定为`trading_day`，第二列假定为`trade_time`")
        else:
            raise ValueError("`time_col`必须是一个字符串或两个字符串：交易时间，或者交易日和交易时间的组合。")
        if hasattr(self, "products"):
            for product in self.products:
                df = self.data[product]
                self.data[product] = df.reset_index().set_index(self.time_col)
                self.logger.info(f"将{product}的索引设置为{self.time_col}")

    def add_data(self, product: ProductBase, df: pd.DataFrame|str, futures_adjust_col: Optional[List[str]] = None):
        if isinstance(df, str):
            assert os.path.exists(df), "数据文件不存在。"
            self.logger.info(f"{product}的数据文件开始加载: {df}")
            if df.endswith('.parquet'):
                df = pd.read_parquet(df)
            elif df.endswith('.csv'):
                df = pd.read_csv(df)
            elif df.endswith('.xlsx'):
                df = pd.read_excel(df)
            else:
                raise ValueError(f"不支持的数据格式：{df}")
            self.logger.info(f"{product}的数据文件加载完成，数据行数: {len(df)}")
        if df.empty:
            self.logger.warning(f"{product}的数据为空，跳过添加。")
            return
        if isinstance(product, Futures):
            futures_adjust_col = futures_adjust_col or self.futures_adjust_col
            if futures_adjust_col:
                futures_adjust_col_adjusted = [col + '_adjusted' for col in futures_adjust_col]
                if any(col not in df.columns for col in futures_adjust_col_adjusted):
                    try:
                        assert 'adjustment_mul' in df.columns
                        assert 'adjustment_add' in df.columns
                    except:
                        message = f"{product}的数据中缺少调整列`adjustment_mul`和`adjustment_add`，无法进行价格调整。"
                        self.logger.error(message)
                        raise AssertionError(message)
                    for col, col_adj in zip(futures_adjust_col, futures_adjust_col_adjusted):
                        df[col_adj] = df[col] * df['adjustment_mul'] + df['adjustment_add']
                        self.logger.info(f"{product}的`{col}`列已进行价格调整, 新列名为`{col_adj}`。")
        if self.time_col_num == 1:
            try:
                assert self.time_col[0] in df.columns
            except:
                self.logger.error(f"{product}的数据中缺少时间列{self.time_col[0]}，无法设置索引。")
                raise AssertionError(f"{product}的数据中缺少时间列{self.time_col[0]}，无法设置索引。")
            try:
                df[self.time_col[0]] = pd.to_datetime(df[self.time_col[0]])
                self.logger.info(f"将{product}的时间列{self.time_col[0]}转换为datetime格式")
            except:
                self.logger.error(f"将{product}的时间列{self.time_col[0]}转换为datetime格式失败")
                raise TypeError(f"无法将{product}的{self.time_col[0]}转换为datetime格式")
        elif self.time_col_num == 2:
            try:
                assert self.time_col[0] in df.columns
            except:
                self.logger.error(f"{product}的数据中缺少时间列{self.time_col[0]}，无法设置索引。")
                raise AssertionError(f"{product}的数据中缺少时间列{self.time_col[0]}，无法设置索引。")
            try:
                df[self.time_col[0]] = pd.to_datetime(df[self.time_col[0]])
                self.logger.info(f"将{product}的时间列{self.time_col[0]}转换为datetime格式")
            except:
                self.logger.error(f"将{product}的时间列{self.time_col[0]}转换为datetime格式失败")
                raise TypeError(f"无法将{product}的{self.time_col[0]}转换为datetime格式")
            try:
                assert self.time_col[1] in df.columns
            except:
                self.logger.error(f"{product}的数据中缺少时间列{self.time_col[1]}，无法设置索引。")
                raise AssertionError(f"{product}的数据中缺少时间列{self.time_col[1]}，无法设置索引。")
            try:
                df[self.time_col[1]] = pd.to_datetime(df[self.time_col[1]])
                self.logger.info(f"将{product}的时间列{self.time_col[1]}转换为datetime格式")
            except:
                self.logger.error(f"将{product}的时间列{self.time_col[1]}转换为datetime格式失败")
                raise TypeError(f"无法将{product}的{self.time_col[1]}转换为datetime格式")
        self.data[product] = df.reset_index().set_index(self.time_col)
        self.logger.info(f"将{product}的索引设置为{self.time_col}")
        self.data_freq[product] = pd.Series(self.data[product].index.get_level_values(self.time_col_num - 1).sort_values().diff().dropna()).mode()[0]
        self.logger.info(f"{product}的数据频率为{self.data_freq[product]}")
        self.products = set(self.data.keys())
        self.product_mapping[product.name] = product

    def calc_interval_return(self, interval: int = 1, price_col: str = 'close_price_adjusted') -> pd.DataFrame:
        returns = {}
        for c, df in self.data.items():
            assert price_col in df.columns, f"{price_col} not in DataFrame columns for contract {c}"
            returns[c] = df[price_col].pct_change(periods=interval).shift(-interval)
        return pd.DataFrame(returns)
    
    def calc_daily_return(self, price_col: str = 'open_price', date_index: bool = False,
                          return_freq: pd.Timedelta|int = pd.Timedelta('1 day'),
                          daily_anchors: Optional[str|pd.Timedelta|List[pd.Timedelta|str]] = None) -> pd.DataFrame:
        daily_returns = {}
        for c, df in self.data.items():
            data_freq = self.data_freq[c]
            daily_return_c = daily_return(df, price_col=price_col, data_freq=data_freq,
                                          return_freq=return_freq, daily_anchors=daily_anchors)
            if date_index and len(daily_return_c.index.names) == 2:
                daily_return_c = daily_return_c.droplevel(1)
            daily_returns[c] = daily_return_c
        return pd.DataFrame(daily_returns)

    def calc_return(self, price_col: str = 'close_price', date_index: bool = False, 
                    time_cols: Optional[str|List[str]] = ['trading_day', 'trade_time'], 
                    calc_freq: Optional[str|pd.Timedelta] = None, return_freq: Optional[str|pd.Timedelta] = None,
                    continuous_calc: bool = True, delta_return: bool = False, log_return: bool = False,
                    daily_anchors: Optional[str|pd.Timedelta|List[pd.Timedelta|str]] = None) -> tuple[pd.DataFrame, bool, bool]:
        
        self.logger.info(f"收益率是否按日期而非时间索引: {date_index}")

        assert not (delta_return and log_return), "`delta_return`和`log_return`不能同时为True。"
        self.logger.info(f"是否计算百分比收益率: {delta_return}")
        self.logger.info(f"是否计算对数收益率: {log_return}")

        factor_freq = pd.Series(self.factor_freq.values()).unique()
        factor_freq = factor_freq[0] if len(factor_freq) == 1 else None
        assert factor_freq is None or isinstance(factor_freq, pd.Timedelta)
        self.logger.info(f"因子池中的因子有共同频率: {factor_freq}")

        data_freq = pd.Series(self.data_freq.values()).unique()
        data_freq = data_freq[0] if len(data_freq) == 1 else None
        assert data_freq is None or isinstance(data_freq, pd.Timedelta)
        self.logger.info(f"数据池中的数据有共同频率: {data_freq}")

        if calc_freq is None:
            calc_freq = factor_freq if factor_freq is not None else data_freq
        elif isinstance(calc_freq, str):
            calc_freq = pd.Timedelta(calc_freq)
        self.logger.info(f"计算频率为: {calc_freq}")
        
        if return_freq is None:
            return_freq = factor_freq if factor_freq is not None else data_freq
        elif isinstance(return_freq, str):
            return_freq = pd.Timedelta(return_freq)
        self.logger.info(f"收益率频率为: {return_freq}")

        if return_freq is not None and return_freq.total_seconds() % pd.Timedelta('1 day').total_seconds() == 0 and\
            calc_freq is not None and calc_freq.total_seconds() % pd.Timedelta('1 day').total_seconds() == 0 and\
            daily_anchors is not None:
            self.logger.info("收益率频率与计算频率均为一日的整数倍, 且选择距离该日开盘或收盘的固定时间点作为计算点, 采用快速计算方式.")
            self.logger.info(f"选择自开盘后或收盘前某个偏移量作为计算点: {daily_anchors}")
            returns_df = self.calc_daily_return(price_col=price_col, date_index=date_index,
                                                return_freq=return_freq, daily_anchors=daily_anchors)
            step = int(calc_freq / pd.Timedelta('1 day'))
            if step > 1:
                all_dates = returns_df.index.get_level_values(0).unique()
                samp_dates = all_dates[::step]
                returns_df = returns_df.loc[returns_df.index.get_level_values(0).isin(samp_dates)]
            self.logger.info(f"计算完毕, 返回结果长度为 {len(returns_df)}, 起始索引为 {returns_df.index[0]}, 结束索引为 {returns_df.index[-1]}")
            if not delta_return:
                returns_df = returns_df + 1
            if log_return:
                returns_df = pd.DataFrame(np.log(returns_df))
            return (returns_df, delta_return, log_return)
        
        if continuous_calc and data_freq is not None and\
            calc_freq is not None and calc_freq.total_seconds() % data_freq.total_seconds() == 0 and\
            return_freq is not None and return_freq.total_seconds() % data_freq.total_seconds() == 0:
            self.logger.info("连续计算下, 计算频率、收益率频率是数据共同频率的整数倍, 采用快速计算方式.")
            step = int(calc_freq / data_freq)
            interval = int(return_freq / data_freq)
            self.logger.info(f"收益率频率是数据共同频率的 {interval} 倍")
            returns_df = self.calc_interval_return(interval=interval, price_col=price_col)
            returns_df = returns_df[0::step]
            self.logger.info(f"计算完毕, 返回结果长度为 {len(returns_df)}, 起始索引为 {returns_df.index[0]}, 结束索引为 {returns_df.index[-1]}")
            if not delta_return:
                returns_df = returns_df + 1
            if log_return:
                returns_df = pd.DataFrame(np.log(returns_df))
            return (returns_df, delta_return, log_return)

        returns_all = {}
    
        for product, df in self.data.items():
            if price_col not in df.columns:
                raise ValueError(f"DataFrame {product} 中缺少列 {price_col}")
            
            data_freq = self.data_freq[product]

            calc_freq = calc_freq if calc_freq is not None else data_freq
            assert isinstance(calc_freq, pd.Timedelta)

            return_freq = return_freq if return_freq is not None else data_freq
            assert isinstance(return_freq, pd.Timedelta)
            
            if len(df.index.names) == 2:
                pass
            elif len(df.index.names) == 1:
                self.logger.info(f"产品 {product} 的数据索引列长度为 1，将使用 {time_cols} 列作为索引")
                df = df.copy()
                if time_cols and len(time_cols) == 2:
                    df = df.reset_index()
                    df[time_cols[0]] = pd.to_datetime(df[time_cols[0]])#.dt.date
                    df[time_cols[1]] = pd.to_datetime(df[time_cols[1]])
                    df = df.set_index(time_cols)
                else:
                    message = f"新的索引列长度应为2, 现在为 {len(time_cols) if time_cols else 0}"
                    self.logger.error(message); raise AssertionError(message)
                df = df.sort_index()
            else:
                message = f"产品 {product} 索引列长度错误, 应为一或二: {df.index.names}"
                self.logger.error(message); raise AssertionError(message)
            temp_series = df[price_col].droplevel(0)

            offset = process_daily_anchors(data_freq=data_freq, daily_anchors=daily_anchors) if daily_anchors is not None else None
            num_offset_neg = len([1 for off in offset if off < 0]) if offset is not None else None

            all_dates = df.index.get_level_values(0)
            indices_of_next_row_changed = np.concatenate(([-1], np.where(all_dates[:-1] != all_dates[1:])[0]))
            indices_market = sorted(itertools.chain.from_iterable([off + indices_of_next_row_changed + 1 for off in offset])) if offset is not None else None
            calc_step = int(calc_freq / pd.Timedelta('1 day'))
            return_step = int(return_freq / pd.Timedelta('1 day'))
            all_datetimes = df.index.get_level_values(1)
            self.logger.info(f"产品 {product} 计算收益率序列的起始时间共有 {len(all_datetimes)} 个时间点")

            if calc_freq:
                if calc_freq.total_seconds() % pd.Timedelta('1 day').total_seconds() == 0 and offset is not None:
                    assert indices_market is not None
                    assert num_offset_neg is not None
                    keep_indices = [
                        indices_market[p + off]
                        for p in range(0, len(indices_market), calc_step * len(offset))
                        for off in range(len(offset))
                        if p + off < len(indices_market) and p + off > num_offset_neg - 1
                    ]
                    start_datetimes = all_datetimes[0:1].append(all_datetimes[indices_market[calc_step-1::calc_step]])
                    start_datetimes = all_datetimes[keep_indices]
                    self.logger.info(f"产品 {product} 使用的计算频率 {calc_freq} 是一日的倍数, 且采用开盘或收盘时间点")
                else:
                    last_t = all_datetimes[0] - calc_freq # 保证第一个点被选中
                    keep_indices = []
                    for i, t in enumerate(all_datetimes):
                        if t >= last_t + calc_freq:
                            keep_indices.append(i)
                            last_t = t
                    start_datetimes = all_datetimes[np.array(keep_indices)]
                self.logger.info(f"产品 {product} 使用计算频率 {calc_freq}, 起始时间缩减到共有 {len(start_datetimes)} 个时间点")
            else:
                start_datetimes = all_datetimes
                keep_indices = None
            start_prices = temp_series.reindex(start_datetimes)
            assert len(start_prices) == len(start_datetimes), "start_prices 和 start_datetimes 长度不一致。"

            if return_freq.total_seconds() % pd.Timedelta('1 day').total_seconds() == 0 and offset is not None:
                assert indices_market is not None
                assert num_offset_neg is not None
                indices = [
                    indices_market[p + off]
                    for p in range(return_step * len(offset), len(indices_market), calc_step * len(offset))
                    for off in range(len(offset))
                    if p + off < len(indices_market) and p + off > return_step * len(offset) + num_offset_neg - 1
                ]
                end_datetimes = all_datetimes[indices]
                len_diff = len(start_datetimes) - len(end_datetimes)
                assert len_diff >= 0, "start_datetimes 长度不得比 end_datetimes 短。"
                if len_diff > 0:
                    end_datetimes = end_datetimes.append(all_datetimes[indices_market[-len_diff:]] + return_freq)
                self.logger.info(f"产品 {product} 使用的收益率频率 {return_freq} 是一日的倍数, 且采用开盘或收盘时间点")
            else:
                if continuous_calc and\
                    return_freq.total_seconds() % data_freq.total_seconds() == 0:
                    off = int(return_freq / data_freq)
                    base_indices = keep_indices if keep_indices is not None else list(range(len(all_datetimes)))
                    end_keep_indices = [idx + off for idx in base_indices if idx + off < len(all_datetimes)]
                    end_datetimes = all_datetimes[end_keep_indices]
                    len_diff = len(start_datetimes) - len(end_datetimes)
                    assert len_diff >= 0, "start_datetimes 长度不得比 end_datetimes 短。"
                    if len_diff > 0:
                        end_datetimes = end_datetimes.append(all_datetimes[-len_diff:] + return_freq)
                else:
                    end_datetimes = start_datetimes + return_freq

            assert len(start_datetimes) == len(end_datetimes), "start_datetimes 和 end_datetimes 长度不一致。"
            
            end_prices = temp_series.reindex(end_datetimes)
            assert len(end_prices) == len(end_datetimes), "end_prices 和 end_datetimes 长度不一致。"
            
            raw_return = end_prices.values / start_prices.values
            
            if date_index:
                index = df.index[df.index.get_level_values(1).isin(start_datetimes)].get_level_values(0)
                assert len(index) == len(start_datetimes), "index 和 start_datetimes 长度不一致。"
                final_series = pd.Series(raw_return, index=index)
                self.logger.info(f"产品 {product} 采用日期索引的收益率序列计算完毕")
            else:
                final_series = pd.Series(raw_return, index=df.index[np.array(keep_indices)] if keep_indices else df.index)
            
            if delta_return:
                final_series = final_series - 1
            elif log_return:
                final_series = np.log(final_series)
                
            returns_all[product] = final_series

        returns_df = pd.DataFrame(returns_all)
        return (returns_df, delta_return, log_return)

    def calc_factor_freq(self, data: pd.DataFrame, name: Optional[str] = None) -> Optional[pd.Timedelta]:
        
        if name is None:
            name = 'Factor_' + str(len(self.factor_freq))

        all_freqs = {}

        if isinstance(data.index, pd.MultiIndex):
            # 确保第一层是datetime(date)，第二层是datetime
            data.index = pd.MultiIndex.from_arrays([
                pd.to_datetime(data.index.get_level_values(0)),
                pd.to_datetime(data.index.get_level_values(1))
            ])
        elif not isinstance(data.index, pd.DatetimeIndex):
            data.index = pd.to_datetime(data.index)

        for product_name in data.columns:
            assert product_name in self.products
            freq_series = data[product_name]
            if len(freq_series) > 0:
                if len(freq_series.index) > 1:
                    all_freqs[product_name] = pd.Series(freq_series.index.get_level_values(len(freq_series.index.names) - 1).sort_values().diff().dropna()).mode()[0]
                    self.logger.info(f"产品 {product_name} 的因子 {name} 频率为 {all_freqs[product_name]}")
                else:
                    self.logger.warning(f"产品 {product_name} 因子 {name} 只有一个数据点，无法确定频率。")
            else:
                self.logger.warning(f"产品 {product_name} 因子 {name} 没有数据。")
        if all_freqs:
            self.factor_freq[name] = pd.Series(all_freqs.values()).mode()[0]
            for product_name in all_freqs:
                if all_freqs[product_name] != self.factor_freq[name]:
                    self.logger.warning(f"产品 {product_name} 的因子 {name} 频率 {all_freqs[product_name]} 与整体因子频率 {self.factor_freq[name]} 不符。")
            return self.factor_freq[name]
        else:
            return None
        
    def calc_factor(self, factors):
        if isinstance(factors, FactorGrid):
            factors = factors.get_factor_list()
        elif isinstance(factors, Callable):
            factors = [('Factor_' + str(len(self.factor_data)), factors)]
        elif isinstance(factors, list) and factors and isinstance(factors[0], Callable):
            assert all(isinstance(factor, Callable) for factor in factors)
            factors = [('Factor_' + str(len(self.factor_data) + idx), factors[idx]) for idx in range(len(factors))]
        elif isinstance(factors, tuple):
            factors = [factors]
        elif isinstance(factors, np.ndarray):
            factors = factors.flatten().tolist()
        assert isinstance(factors, list)
        assert all(isinstance(factor, tuple) for factor in factors)
        assert all(isinstance(factor[0], str) for factor in factors)
        assert all(isinstance(factor[1], Callable) for factor in factors)
        
        for factor_name, factor_func in tqdm(factors, desc='Factor processing'):
            factors_df = factor_func(self.data, self.data_freq)
            if not factors_df.empty:
                self.factor_data[factor_name] = factors_df
                self.calc_factor_freq(data=factors_df, name=factor_name)
            else:
                message = f"因子 {factor_name} 未能计算出任何数据。"
                self.logger.error(message)
                raise ValueError(message)
        return self.factor_data
    
    def calc_rank(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.rank(axis=1, method='average', na_option='keep', pct=True)

    def calc_ic(self, factors: str|List[str]|FactorGrid|tuple|List[tuple], 
                return_price_col: str = 'close_price_adjusted',
                return_freq: Optional[str|pd.Timedelta] = None,
                return_daily_anchors: Optional[Any] = None,
                start_date: Optional[str] = None, end_date: Optional[str] = None) -> tuple[pd.DataFrame, pd.DataFrame]:
        
        if isinstance(factors, FactorGrid):
            factors = factors.get_factor_name_list()
        elif isinstance(factors, str):
            factors = [factors]
        elif isinstance(factors, tuple):
            assert isinstance(factors[0], str)
            factors = [factors[0]]
        elif isinstance(factors, list) and factors and isinstance(factors[0], tuple):
            assert all(isinstance(t, tuple) for t in factors)
            assert all(len(t) == 2 for t in factors)
            assert all(isinstance(fn, str) for fn, _ in factors)
            factors = [fn for fn, _ in factors]
        assert isinstance(factors, list)

        shift_one = True
        if return_daily_anchors is not None:
            if isinstance(return_daily_anchors, list) or isinstance(return_daily_anchors, tuple):
                assert len(return_daily_anchors) == 1, "IC测试仅支持单一时间点作为每日锚点。"
                return_daily_anchors = return_daily_anchors[0]
            assert isinstance(return_daily_anchors, str) or isinstance(return_daily_anchors, pd.Timedelta)
            if return_daily_anchors == 'close_market':
                shift_one = False
                        
        ic_series = {}
        ic_stats = {}
        for factor_name in factors:
            assert isinstance(factor_name, str)
            factor_rank = self.calc_rank(self.factor_data[factor_name])
            return_df, _, _ = self.cache_return_by_factor_name(factor_name, price_col=return_price_col, 
                                                               return_freq=return_freq, daily_anchors=return_daily_anchors)
            if shift_one:
                return_df = return_df.shift(-1)
            return_rank = self.calc_rank(return_df)
            dt_index = factor_rank.index.intersection(return_rank.index)
            start_date = start_date if start_date is not None else self.start_date
            end_date = end_date if end_date is not None else self.end_date
            if start_date is not None:
                dt_index = dt_index[dt_index >= start_date]
            if end_date is not None:
                dt_index = dt_index[dt_index <= end_date]
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
            ic_series[factor_name] = pd.Series(ic, index=dt_index)
            avg_coverage = np.mean(coverage)
            stats_df = self.ic_stats(ic_series[factor_name])
            stats_df['avg_coverage'] = avg_coverage
            ic_stats[factor_name] = stats_df
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
    
    def cache_return(self, price_col: str = 'close_price_adjusted',
                     date_index: bool = False, return_freq: Optional[str|pd.Timedelta] = None, daily_anchors: Optional[str|pd.Timedelta|List[pd.Timedelta|str]] = None,
                     calc_freq: Optional[str|pd.Timedelta] = None) -> tuple[pd.DataFrame, bool, bool]:
        return_label = (return_freq, calc_freq, price_col, date_index, daily_anchors)
        if return_label in self.return_data and\
            set(self.return_data[return_label][0].columns) == self.products:
            return self.return_data[return_label]
        else:
            outcome = self.calc_return(price_col=price_col, return_freq=return_freq, calc_freq=calc_freq, 
                                       daily_anchors=daily_anchors, date_index=date_index)
            self.return_data[return_label] = outcome
            return outcome
        
    def cache_return_by_factor_name(self, factor_name: str, price_col: str = 'close_price_adjusted',
                     date_index: Optional[bool] = None, return_freq: Optional[str|pd.Timedelta] = None,
                     daily_anchors: Optional[str|pd.Timedelta|List[pd.Timedelta|str]] = None,
                     calc_freq: Optional[str|pd.Timedelta] = None) -> tuple[pd.DataFrame, bool, bool]:
        return_freq = return_freq if return_freq is not None else self.factor_freq[factor_name]
        calc_freq = calc_freq if calc_freq is not None else self.factor_freq[factor_name]
        date_index = date_index if date_index is not None else \
            True if self.factor_freq[factor_name] == pd.Timedelta('1 day') else False
        return self.cache_return(price_col=price_col, date_index=date_index, daily_anchors=daily_anchors,
                                 return_freq=return_freq, calc_freq=calc_freq)

    def sift_product(self, method: Optional[str] = None, 
                     volume_threshold: Optional[float] = None, volume_col: Optional[str] = None,
                     in_place: bool = False, in_place_reset: bool = True,
                    #  sift_freq: Optional[str|pd.Timedelta] = None,
                     start_date: Optional[str|pd.Timestamp] = None,
                     end_date: Optional[str|pd.Timestamp] = None) -> List[ProductBase]|Set[ProductBase]:
        if in_place_reset:
            self.products = set(self.data.keys())
        if method is None:
            return self.products
        elif method == 'volume':
            if volume_threshold is None:
                raise ValueError("volume_threshold is required for volume method")
            if volume_col is None:
                raise ValueError("volume_col is required for volume method")
            if start_date is None:
                if self.start_date is not None:
                    start_date = self.start_date
                if start_date is None:
                    start_date_list = [self.data[product]['trading_day'][0] for product in self.products]
                    start_date_list = np.unique(start_date_list)
                    if len(start_date_list) > 1:
                        raise ValueError("Multiple start dates found in data. Please specify start_date.")
            else:
                start_date = pd.to_datetime(start_date)
            if end_date is None:
                if self.end_date is not None:
                    end_date = self.end_date
                if end_date is None:
                    end_date_list = [self.data[product]['trading_day'][-1] for product in self.products]
                    end_date_list = np.unique(end_date_list)
                    if len(end_date_list) > 1:
                        raise ValueError("Multiple end dates found in data. Please specify end_date.")
            else:
                end_date = pd.to_datetime(end_date)
            if start_date is not None and end_date is not None:
                assert isinstance(start_date, pd.Timestamp)
                assert isinstance(end_date, pd.Timestamp)
                assert start_date <= end_date
            sift_dict = {}
            for product in self.products.copy():
                volume_seq = self.data[product][volume_col]
                if start_date is not None:
                    volume_seq = volume_seq[volume_seq.index.get_level_values(0) >= start_date]
                if end_date is not None:
                    volume_seq = volume_seq[volume_seq.index.get_level_values(0) <= end_date]
                sift_dict[product] = volume_seq.sum()
            sift_dict_sorted = dict(sorted(sift_dict.items(), key=lambda x: x[1]))
            threshold_idx = int(len(sift_dict_sorted) * volume_threshold)
            products_to_keep = set(list(sift_dict_sorted.keys())[:threshold_idx])
            if in_place:
                self.products = products_to_keep
                return self.products
            else:
                return products_to_keep
        else:
            raise ValueError(f"Unknown sift method: {method}")

    def group_classes(self, factor_name: str, n_groups: int = 5, plot_flag: bool = False, 
                      start_date: Optional[str|pd.Timestamp] = None, end_date: Optional[str|pd.Timestamp] = None,
                      return_price_col: str = 'close_price_adjusted',
                      return_daily_anchors: Optional[str|pd.Timedelta|List[pd.Timedelta|str]] = None,
                      return_freq: Optional[str|pd.Timedelta] = None,
                      plot_n_group_list: Optional[List[int]] = None) -> \
        Tuple[Dict[str, Dict[str, List[ProductBase]]], Dict[str, Dict[str, float]], pd.DataFrame]:
        """
        For each datetime, split contracts into n_groups groups.
        Each group is a dict: {datetime_str: [contract names]}.
        n_groups: number of groups to split into (default: 5)
        """

        shift_one = True
        if return_daily_anchors is not None:
            if isinstance(return_daily_anchors, list) or isinstance(return_daily_anchors, tuple):
                assert len(return_daily_anchors) == 1, "分类等权回测仅支持单一时间点作为每日锚点。"
                return_daily_anchors = return_daily_anchors[0]
            assert isinstance(return_daily_anchors, str) or isinstance(return_daily_anchors, pd.Timedelta)
            if return_daily_anchors == 'close_market':
                shift_one = False

        returns, delta_return, _ = self.cache_return_by_factor_name(factor_name, price_col=return_price_col,
                                                                    return_freq=return_freq, daily_anchors=return_daily_anchors)
        if shift_one:
            returns = returns.shift(-1)

        if not delta_return:
            returns = returns - 1

        assert factor_name in self.factor_data, "Factor name must be in factor_data."
        factor_df = self.factor_data[factor_name]

        # Plot adjustment for group numbers
        plot_n_group_list = [n_groups + n_group if n_group < 0 else n_group for n_group in plot_n_group_list] if plot_n_group_list else None

        group_names = ['group_' + str(i) for i in range(n_groups)]
        group_names = group_names[::-1]
        groups = {name: {} for name in group_names}
        returns_groups = {name: {} for name in group_names}

        start_date = pd.to_datetime(start_date) if start_date is not None else None
        end_date = pd.to_datetime(end_date) if end_date is not None else None
        
        for dt, row in factor_df.iterrows():
            dt_str = dt
            sifted_products = self.sift_product(method='volume', volume_threshold=0.6,
                                                volume_col='volume', start_date=dt, end_date=dt)
            sorted_products = row.dropna().sort_values(ascending=False)
            sorted_products = sorted_products[sorted_products.index.isin(sifted_products)]
            n = len(sorted_products)
            idx = list(sorted_products.index)
            
            # Split contracts into n_groups groups
            if n > 0:
                idx_array = np.asarray(idx)
                split = np.array_split(idx_array, min(n, n_groups))
                
                # Fill groups from bottom to top (ascending order of factor values)
                for i, group_products in enumerate(split):
                    group_idx = n_groups - 1 - i  # Reverse order: bottom group first
                    groups[group_names[group_idx]][dt_str] = list(group_products)
                    returns_groups[group_names[group_idx]][dt_str] = np.mean(np.asarray(returns.loc[dt_str][group_products].values, dtype=float))
            
            # Fill remaining groups (if n < n_groups) with empty lists
            for i in range(min(n, n_groups), n_groups):
                groups[group_names[i]][dt_str] = []
                returns_groups[group_names[i]][dt_str] = np.nan

        report_groups = {}
        for name in group_names:
            dates = list(returns_groups[name].keys()) if returns_groups[name] else []
            dates = [date for date in dates if start_date <= date] if start_date else dates
            dates = [date for date in dates if date <= end_date] if end_date else dates
            returns = [returns_groups[name][date] for date in dates]
            returns_series = pd.Series(returns).dropna()
            cumulative_returns = (1 + returns_series).cumprod()
            metrics = {
            'Total Return': (cumulative_returns.iloc[-1] - 1) * 100 if len(cumulative_returns) > 0 else 0,
            'Annual Return': ((cumulative_returns.iloc[-1]) ** (252 / len(cumulative_returns)) - 1) * 100 if len(cumulative_returns) > 1 else 0,
            'Volatility': pd.Series(returns).std() * np.sqrt(252) * 100,
            'Sharpe Ratio': (pd.Series(returns).mean() * 252) / (pd.Series(returns).std() * np.sqrt(252)) if pd.Series(returns).std() != 0 else 0,
            'Max Drawdown': ((cumulative_returns.cummax() - cumulative_returns) / cumulative_returns.cummax()).max() * 100 if len(cumulative_returns) > 0 else 0,
            'Calmar Ratio': ((cumulative_returns.iloc[-1] ** (252 / len(cumulative_returns)) - 1) * 100) / (((cumulative_returns.cummax() - cumulative_returns) / cumulative_returns.cummax()).max() * 100) if ((cumulative_returns.cummax() - cumulative_returns) / cumulative_returns.cummax()).max() != 0 else 0,
            'Win Rate': (pd.Series(returns) > 0).sum() / len(pd.Series(returns)) * 100 if len(pd.Series(returns)) > 0 else 0,
            'Mean Return': pd.Series(returns).mean() * 100,
            'Skewness': pd.Series(returns).skew(),
            'Kurtosis': pd.Series(returns).kurtosis(),
            }
            name = int(name.split('_')[-1])
            report_groups[name] = pd.Series(metrics)
        
        report_df = pd.DataFrame(report_groups).T.sort_index()  # Convert to DataFrame, transpose, and sort by name
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
            for name in group_names:
                if plot_n_group_list is not None and name.split('_')[-1] not in [str(n) for n in plot_n_group_list]:
                    continue
                dates = list(returns_groups[name].keys()) if returns_groups[name] else []
                dates = [date for date in dates if start_date <= date] if start_date else dates
                dates = [date for date in dates if date <= end_date] if end_date else dates
                returns = [returns_groups[name][date] for date in dates]
                cumulative_returns = []
                prev_value = 10000
                for ret in returns:
                    if not np.isnan(ret):
                        prev_value = prev_value * (1 + ret)
                    cumulative_returns.append(prev_value)
                plt.plot([str(date) for date in dates], cumulative_returns, label=name)
            plt.xlabel('Date')
            plt.ylabel('Average Next Day Open Return')
            plt.title(f'Average Next Day Open Return by Factor Groups for {factor_name}')
            plt.legend()
            # Only show every nth tick to reduce crowding
            n_ticks = 10
            assert len(dates) > 0, "No dates available for plotting."
            tick_indices = np.linspace(0, len(dates) - 1, min(n_ticks, len(dates)), dtype=int)
            plt.xticks(ticks=[str(dates[i]) for i in tick_indices], rotation=45)
            plt.tight_layout()
            plt.show()

        return groups, returns_groups, report_df
    
def process_daily_anchors(data_freq: pd.Timedelta, daily_anchors: Any) -> List[int]:
    if not isinstance(daily_anchors, list) and not isinstance(daily_anchors, tuple):
        daily_anchors = [daily_anchors]
    offset = []
    for idx in range(len(daily_anchors)):
        to = daily_anchors[idx]
        if isinstance(to, str):
            if to == 'open_market':
                off = 0
                offset.append(off)
                continue
            elif to == 'close_market':
                off = -1
                offset.append(off)
                continue
            else:
                try:
                    to = pd.Timedelta(to)
                except:
                    raise ValueError(f"无法将字符串{to}转换为pd.Timedelta")
        if isinstance(to, pd.Timedelta):
            off = int(to.total_seconds() / data_freq.total_seconds())
            if off < 0:
                off = off - 1
        else:
            raise ValueError(f"Invalid `daily_anchors`: {to}")
        offset.append(off)
    return offset

def daily_return(df: pd.DataFrame, price_col: str = 'close_price', 
                 data_freq: Optional[pd.Timedelta] = None,
                 daily_anchors: Optional[str|pd.Timedelta|List[pd.Timedelta|str]] = None,
                 return_freq: pd.Timedelta|int = pd.Timedelta('1 day')) -> pd.Series:
    daily_price = df.groupby('trading_day')[price_col]
    assert daily_anchors is not None
    offset = None
    if daily_anchors is not None:
        assert data_freq is not None
        offset = process_daily_anchors(data_freq, daily_anchors)
    if isinstance(return_freq, pd.Timedelta):
        assert return_freq.total_seconds() % pd.Timedelta('1 day').total_seconds() == 0
        return_freq = int(return_freq.total_seconds() / pd.Timedelta('1 day').total_seconds())
        if daily_anchors is not None:
            return_freq = return_freq * len(offset)
    assert isinstance(return_freq, int) and return_freq > 0
    returns = daily_price.nth(offset).pct_change(periods=return_freq).shift(-return_freq)
    assert isinstance(returns, pd.Series)
    return returns

def get_factor_tester(start_date: Optional[str] = None, end_date: Optional[str] = None) -> FactorTester:
    parquet_dir = '../data/main_mink/'
    file_list = [
        os.path.join(parquet_dir, f)
        for f in os.listdir(parquet_dir)
        if f.endswith('.parquet') and '_S' not in f and '-S' not in f
    ]
    
    tester = FactorTester(file_list, #start_date='2025-01-01', 
                    end_date='2025-05-30', 
                    futures_flag=True, futures_adjust_col=['close_price', 'open_price', 'highest_price', 'lowest_price'])
    
    return tester

def factor_test(factors: FactorGrid|tuple[str, Callable]|List[tuple[str, Callable]],
                n_groups: int = 5, plot_n_group_list: Optional[List[int]] = None,):
    
    # import cProfile
    # import pstats

    # profiler = cProfile.Profile()
    # profiler.enable()

    tester = get_factor_tester()
    tester.calc_factor(factors)

    ic_series, stats = tester.calc_ic(factors=factors, return_price_col='open_price_adjusted',
                              return_daily_anchors='open_market')#, return_freq='5 days')
    # import matplotlib.pyplot as plt

    # plt.figure(figsize=(14, 6))
    # for col in ic_series.columns:
    #     plt.plot(ic_series.index, ic_series[col], label=col, alpha=0.7)
    # plt.xlabel('Date')
    # plt.ylabel('IC')
    # plt.title('IC Series Over Time')
    # plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    # plt.grid(True, alpha=0.3)
    # plt.tight_layout()
    # plt.show()

    print('IC Stats Median t_stat:', stats.loc['t_stat'].median())
    if len(stats.columns) >= 4:
        stats = stats.T.sort_values('t_stat', ascending=False)
        mid = len(stats.columns)//2
        stats = pd.concat([
            stats[:2].T, stats[mid:mid+1].T, stats[-1:].T
        ], axis=1)
    print('Selected by t_stat:\n', stats)
    factor_names = stats.columns.tolist()
    
    loop_bool = True
    while loop_bool:
        which_factor = input(f'选择哪一个因子进行分类回测 (1 - {len(factor_names)}): ')
        if which_factor.isdigit() and 1 <= int(which_factor) <= len(factor_names):
            which_factor = int(which_factor) - 1
            groups, returns_groups, _ = tester.group_classes(factor_names[which_factor], 
                                                plot_flag=True, n_groups=n_groups, plot_n_group_list=plot_n_group_list,
                                                start_date='2025-01-01', end_date='2025-12-31',
                                                return_price_col='open_price_adjusted', return_daily_anchors='open_market'
                                                )
        else:
            loop_bool = False

    # # Get the earliest five dates from the 'top' group
    # earliest_dates = sorted(groups['group_0'].keys())[:5]
    # for date in earliest_dates:
    #     print(date, groups['group_0'][date])
    #     print(date, returns_groups['group_0'][date])
    #     pass

    # profiler.disable()
    # # 输出分析结果
    # stats = pstats.Stats(profiler)
    # stats.sort_stats('cumulative')  # 按累计时间排序
    # stats.print_stats(20)  # 显示前20个耗时最多的函数