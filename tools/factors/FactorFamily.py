# =============================================================================
# tools/factors/FactorFamily.py
# 因子族模块
#
# FactorFamily 是因子系统的核心基类，负责：
#   1. func()            — 遍历品种列表并汇总时序信号（支持多线程）
#   2. func_timeseries() — 子类实现，计算单品种因子时序
#   3. sync_signal()     — 将数据对齐到等间隔信号时间点（核心对齐逻辑）
#   4. _get_sync_signal_index() — 构建全局信号索引（复杂边界处理）
#   5. get_factor() / get_factors() — 创建 Factor 实例
#   6. test()            — 一键运行 IC / 分组收益测试并持久化结果
#
# 内置子类：
#   Returns — 计算下期/当期收益率（OPEN-to-OPEN 或 CLOSE-to-CLOSE）
# =============================================================================
import os
import threading
import pandas as pd
from functools import partial
from weakref import WeakValueDictionary
from contextvars import ContextVar
from typing import TYPE_CHECKING, List, Optional, Sequence, Any, Tuple, Callable

from tqdm import tqdm

from tools.factors.Factor import Factor
from tools.products.Product import Product
from tools.factors.FactorTester import FactorTester, get_factor_tester
from tools import SerialObject, DataFreq, DataMeta, DataColumn
from tools.parameters import Parameter, WindowParam, DataColumnParam, TypeParam
from tools.factors.Parameters import StartCalcPointParam, FactorFreqParam, FactorNextPeriodReturns, ReverseParam

from Settings import sift_volume_ratio, default_plot_test_end_date, default_plot_test_start_date, default_test_end_date, default_test_start_date, factor_info_path

# 每个执行上下文（线程/协程）的活跃 FactorTester，由 test() 或服务端路由设置。
# 通过 ContextVar 保证并发安全：每个请求线程拥有独立的值，互不干扰。
_active_tester: ContextVar[Optional['FactorTester']] = ContextVar('_active_tester', default=None)

class FactorFamily(SerialObject):
    """
    因子族基类。

    每个子类对应一种因子计算逻辑，通过重写 func_timeseries 实现单品种信号。
    FactorFamily 负责：
      - 批量调用 func_timeseries 汇总多品种 DataFrame（func）
      - 管理参数集合（params / _params_list）
      - 构建信号时间索引（_get_sync_signal_index）并对数据对齐（sync_signal）
      - 创建 Factor 实例（get_factor / get_factors）
      - 驱动完整的 IC + 分组收益测试流程（test）

    类属性：
        math_expr            (str)  : 因子公式的 LaTeX 字符串，供前端展示
        description_sections (list) : 因子结构化说明，供前端展示
        params               (list) : 本族使用的参数对象列表（子类应覆盖）
    """
    _instances = WeakValueDictionary()
    math_expr: str = ""       # 子类可覆盖，填写 LaTeX 格式的数学表达式
    chinese_name: str = ""    # 子类可覆盖，填写因子中文名称，供前端显示和搜索
    description_sections: List[dict] = []
    _serial_map = {}
    params: List[Parameter] = []

    def __new__(cls, alias: Optional[str] = None, *args, **kwargs):
        # 若未提供 alias，则使用类名作为默认别名
        alias=alias if alias else cls.__name__
        return super().__new__(cls, type_alias='FF', alias=alias)

    def __init__(self, alias: Optional[str] = None, factor_single_use: bool = False):
        """
        初始化 FactorFamily。

        参数：
            alias            : 别名，默认为类名
            factor_single_use: 若为 True，则由本族创建的 Factor 均为 single_use 临时对象
        """
        if not hasattr(self, '_initialized'):
            alias=alias if alias else self.__class__.__name__
            super().__init__(type_alias='FF', alias=alias)
            self._runtime_ctx = threading.local()  # 运行时线程本地上下文（如当前 signal freq）
            self.params.append(FactorFreqParam)   # 所有子类默认包含信号频率参数 F
            self.params.append(ReverseParam)       # 所有子类默认包含反转参数 $Rev（1/True=-反向；0/False=正向）
            self.params_dict = {param.alias: param for param in self.params}
            self.set_default_params()             # 以各参数默认值初始化 _params_list
            self.factors: List[Factor] = []       # 最近一批生成的 Factor 实例
            self.factor_single_use = factor_single_use

    def func(self, products: Sequence[Product], *args, **kwargs) -> pd.DataFrame:
        """
        批量计算因子信号，返回多品种 DataFrame。

        流程：
          1. 品种数 ≤200 时串行调用 func_timeseries（带进度条）
          2. 品种数 >200 时用 ThreadPoolExecutor(8) 并行计算
          3. 按列 concat 合并各品种 Series
          4. 若信号频率为日度倍数，不同品种的交易结束时间可能不同（如 15:00 vs 15:15），
             concat 后同一日期会出现多行 → 自动合并：数据列取第一个非 NaN，子日精度索引取最大值

        参数：
            products : 品种列表
            **kwargs : 转发给 func_timeseries 的参数键值对（即各 Parameter 的 alias→value）

        返回：
            DataFrame，列为 Product，索引为 MultiIndex（信号层 + 精度层）
        """
        # 运行时参数归一化：支持 F/Rev 与 $F/$Rev 混用输入
        kwargs = self._normalize_param_kwargs(**kwargs)
        # 多数因子方法签名使用 F，这里将 $F 映射为 F 供 func_timeseries 使用
        if '$F' in kwargs and 'F' not in kwargs:
            kwargs['F'] = kwargs['$F']
        signal_freq = kwargs.get('F', pd.Timedelta('1d'))
        # 提取反转参数，不转发给 func_timeseries（统一使用 $Rev）
        is_reversed: bool = kwargs.pop('$Rev', False)
        try:
            # 过滤无数据品种（停牌、尚未上市等），避免 func_timeseries 里得到空索引
            valid_products = [p for p in products if not p.get_some_data(copy=False).empty]
            if not valid_products:
                raise ValueError("No products with valid data")
            # 更新活跃 tester 的有效品种集，并使同步索引缓存失效。
            # single_use 辅助族（如 Returns）不永久覆盖用户选定的品种集，
            # 但需要临时切换到当前计算品种（_get_sync_signal_index 从 tester.products 读取），
            # 计算结束后恢复原值。
            tester = _active_tester.get()
            _prev_products = None
            if tester is not None:
                if self.factor_single_use:
                    _prev_products = tester.products  # 保存以便恢复
                tester.products = set(valid_products)
                tester.sync_signal_index = None
                tester.sync_signal_index_replaced = None
            factors = {}
            try:
                if len(valid_products) <= 200:
                    for product in tqdm(valid_products, desc=f"Calculating factor signals"):
                        self._runtime_ctx.signal_freq = signal_freq
                        factors[product] = self.func_timeseries(product, *args, **kwargs)
                else:
                    from concurrent.futures import ThreadPoolExecutor, as_completed
                    def compute_factor(product, *args, **kwargs):
                        self._runtime_ctx.signal_freq = signal_freq
                        return product, self.func_timeseries(product, *args, **kwargs)
                    with ThreadPoolExecutor(max_workers=8) as executor:
                        futures = {executor.submit(compute_factor, product, *args, **kwargs): product for product in valid_products}
                        for future in tqdm(as_completed(futures), total=len(valid_products), desc="Calculating factor signals"):
                            product, factor = future.result(); factors[product] = factor
            finally:
                # single_use 辅助族计算结束后，将 tester.products 恢复为调用前的品种集
                if tester is not None and _prev_products is not None:
                    tester.products = _prev_products
                    tester.sync_signal_index = None
                    tester.sync_signal_index_replaced = None
            # 假设所有 df 的 MultiIndex 具有相同的 level 名称和顺序
            # 先取并集
            all_index = factors[list(factors.keys())[0]].index
            for df in list(factors.values())[1:]:
                all_index = all_index.union(df.index)
            # 然后 reindex 并 concat
            result = pd.concat({k: df.reindex(all_index) for k, df in factors.items()}, axis=1)
            # 日度倍数信号：不同品种交易截止时间不同（如 15:00 vs 15:15），
            # concat 后同一日期会出现多行，需合并为单行
            # 数据列取第一个非 NaN，子日精度索引取最大值
            signal_level_name = next((str(n) for n in result.index.names if str(n).startswith('_SIGNAL@')), None)
            if signal_level_name is not None:
                sub_day_names = [str(n) for n in result.index.names if str(n) != signal_level_name]
                if DataFreq(signal_level_name).is_day_multiple() and sub_day_names:
                    date_key = result.index.get_level_values(signal_level_name)
                    if date_key.duplicated().any():
                        merged = result.groupby(level=signal_level_name).first()
                        sub_arrays = [
                            pd.DatetimeIndex(
                                pd.Series(result.index.get_level_values(n), index=date_key)
                                .groupby(level=0).max().loc[merged.index]
                            )
                            for n in sub_day_names
                        ]
                        merged.index = pd.MultiIndex.from_arrays(
                            [merged.index.values] + sub_arrays,
                            names=[signal_level_name] + sub_day_names
                        )
                        result = merged
            if is_reversed:
                result = -result
            return result
        except Exception as e:
            raise e
    
    def func_timeseries(self, product: Product, *args, **kwargs) -> Any:
        """
        【子类必须重写】计算单品种的因子时序。

        参数：
            product : 品种对象
            **kwargs: 因子参数键值对（由 func 转发）

        返回：
            pd.Series，索引为 MultiIndex，与 func 汇总时保持一致
        """
        raise NotImplementedError("请在子类中实现 `func_timeseries` 方法")

    def set_default_params(self):
        """用各参数默认值初始化 _params_list（仅一组默认参数组合）。"""
        self._params_list = [{p.alias: p.default_value for p in self.params}]

    def _normalize_param_kwargs(self, **kwargs) -> dict:
        """
        归一化参数别名：当输入键不存在时，尝试在带/不带 '$' 形式间互转。

        例如：F -> $F，Rev -> $Rev。
        """
        normalized = {}
        for key, value in kwargs.items():
            target_key = key
            if key == 'Rev':
                target_key = '$Rev'
            if key not in self.params_dict:
                if key.startswith('$') and key[1:] in self.params_dict:
                    target_key = key[1:]
                elif not key.startswith('$') and f'${key}' in self.params_dict:
                    target_key = f'${key}'
            if target_key in normalized and normalized[target_key] != value:
                raise ValueError(f"Conflicting values for parameter {target_key}")
            normalized[target_key] = value
        return normalized

    def change_param_default_value(self, **kwargs):
        """修改指定参数的默认值（同时校验值域）。"""
        kwargs = self._normalize_param_kwargs(**kwargs)
        self._check_in_space(**kwargs)
        for key, value in kwargs.items():
            self.params_dict[key].default_value = value

    def clear_params(self):
        """清空参数组合列表，使 get_factors 不生成任何 Factor。"""
        self._params_list = []

    def _check_in_space(self, **kwargs):
        """校验 kwargs 中每个参数值是否在对应参数的值域内，不在则抛出 ValueError。"""
        kwargs = self._normalize_param_kwargs(**kwargs)
        for key in kwargs:
            if kwargs[key] not in self.params_dict[key]:
                raise ValueError(f"{kwargs[key]} is not in the value space of {key}")

    def add_params(self, **kwargs):
        """
        向 _params_list 追加一组参数组合（已存在则忽略）。

        未指定的参数取其默认值，所有值均经 rectify_value 标准化。
        """
        kwargs = self._normalize_param_kwargs(**kwargs)
        self._check_in_space(**kwargs)
        new_params = {p.alias: p.rectify_value(kwargs[p.alias]) if p.alias in kwargs else p.default_value for p in self.params}
        if new_params not in self._params_list:
            self._params_list.append(new_params)

    def del_params(self, **kwargs):
        """从 _params_list 中删除与 kwargs 匹配的参数组合。"""
        kwargs = self._normalize_param_kwargs(**kwargs)
        self._check_in_space(**kwargs)
        del_params = {p.alias: p.rectify_value(kwargs[p.alias]) if p.alias in kwargs else p.default_value for p in self.params}
        self._params_list = [params for params in self._params_list if params != del_params]

    def set_all_params(self):
        """【子类可选重写】批量设置常用参数组合，不实现时返回 NotImplementedError。"""
        return NotImplementedError("请在子类中实现 `set_all_params` 方法")

    def get_alias(self, **params) -> str:
        """
        根据参数值生成 Factor 的完整别名。

        格式：{家族别名}|{alias1}:{值别名}|{alias2}:{值别名}...
        值别名为空字符串的参数会被跳过，不出现在名称中。
        若无参数则直接返回家族别名。
        """
        parts = []
        for key, value in params.items():
            val_alias = self.params_dict[key].get_value_alias(value)
            if val_alias:
                if key == '$Rev':
                    if val_alias == '1':
                        parts.append(key)
                else:
                    parts.append(f"{key}:{val_alias}")
        params_str = '|'.join(parts)
        return f"{self.alias}|{params_str}" if params_str else self.alias

    def get_factors(self, return_freq: Optional[Any] = None, params_list: Optional[list] = None, **kwargs) -> List[Factor]:
        """
        按 _params_list 中的所有参数组合批量创建 Factor 实例。

        参数：
            return_freq      : 收益率计算频率（覆盖 Factor 默认值）
            params_list      : 若提供，则使用此列表代替 self._params_list（用于 per-user 隔离）
            **kwargs         : 额外参数（如 timezone）

        返回：
            Factor 列表，同时写入 self.factors
        """
        _pl = params_list if params_list is not None else self._params_list
        factors = []
        for params in _pl:
            factor_alias = self.get_alias(**params)
            factor_func = partial(self.func, **params)
            factor = Factor(alias=factor_alias, func=factor_func, family=self, single_use=self.factor_single_use)
            for param_alias, value in params.items():
                self.params_dict[param_alias].register(factor, value)
            if return_freq is not None:
                factor.change_current_return_freq(return_freq)
            factors.append(factor)
        return factors

    def get_factor(self, return_freq: Optional[Any] = None, start_calc_point: Optional[Any] = None, **kwargs) -> Factor:
        """
        创建单个 Factor 实例（支持按 alias 复用已有实例）。

        参数：
            return_freq      : 收益率计算频率
            start_calc_point : 计算起始点
            **kwargs         : Parameter alias→value 键值对（未指定时取默认值）

        返回：
            Factor 实例
        """
        kwargs = self._normalize_param_kwargs(**kwargs)
        self._check_in_space(**kwargs)
        param_vals = {p: p.rectify_value(kwargs[p.alias]) if p.alias in kwargs else p.default_value for p in self.params}
        new_params = {p.alias: param_vals[p] for p in self.params}
        factor_alias = self.get_alias(**new_params)
        factor_func = partial(self.func, **new_params)
        factor = Factor(alias=factor_alias, func=factor_func, param_vals=param_vals, family=self, single_use=self.factor_single_use)
        if return_freq is not None:
            factor.change_current_return_freq(return_freq)
        return factor

    def test(self, categories: Optional['str|List[str]'] = None,
             return_freq: Optional[Any] = None,
             start_calc_point: Optional[Any] = None,
             ic_test_time_range: Optional[Tuple] = None,
             sift_volume_ratio: float = sift_volume_ratio, **kwargs) -> FactorTester:
        """
        一键运行完整测试流程：因子计算 → IC 测试 → 分组收益测试 → 结果持久化。

        流程：
          1. 加载（或新建）因子信息缓存 CSV
          2. 创建 FactorTester，设置时间范围
          3. 调用 calc_factor、calc_ic
          4. 对每个 Factor 调用 test_by_group，并将结果追加写入 CSV

        参数：
            categories       : 品种分类过滤（字符串或列表），None 表示不过滤
            return_freq      : 收益率计算频率
            start_calc_point : 计算起始点
            ic_test_time_range: (start, end)，覆盖全局默认区间
            sift_volume_ratio: 按成交量筛选品种的比例（0~1）

        返回：
            FactorTester 对象（含完整测试结果）
        """
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
        # start_calc_point 通过 tester.start_calc_point（带时区 Timestamp）统一访问
        if start_calc_point is not None:
            tester.start_calc_point = pd.Timestamp(start_calc_point)

        returns_col = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED  # 默认使用次日开盘→开盘收益

        _token = _active_tester.set(tester)
        try:
            factors = self.get_factors(return_freq=return_freq, **kwargs)
            tester.calc_factor(factors)
            tester.calc_ic(returns_col=returns_col)

            for factor in factors:

                _, _, report_df, _, _ = tester.test_by_group(factor, returns_col=returns_col,
                    plot_flag=True, time_range=(default_plot_test_start_date, default_plot_test_end_date),
                    plot_show=False, plot_remark_str=','.join(categories) if categories else None, **kwargs
                    )

                # 将分组回测结果拼入发布报告行
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
        finally:
            _active_tester.reset(_token)

        return tester
    
    def _get_sync_signal_index(self, freq: Any, end_session_skip: bool = True,
                    end_session_gap: pd.Timedelta = pd.Timedelta('3hours'),
                    basepoint: 'str|Callable' = 'last',  # 'last', 'first', '09:01:00'
                    **kwargs) -> pd.Index:
        """
        构建全局信号时间索引。

        该方法确定在给定频率 freq 下，所有品种共享的「应该产生信号」的时间点集合。
        结果被缓存到 current_sync_signal_index，后续 sync_signal 直接复用。

        算法概述：
          1. 从 current_factor_tester 或 self.products 获取品种列表
          2. 只保留上市时间最早的品种（排除新上市品种造成的索引偏差）
          3. 按 basepoint 策略（last/first/时间字符串/可调用函数）确定每日/每周期的基准 bar
          4. 每隔 multiple 个基准 bar 取一个信号点（实现 freq 下采样）
          5. 若 end_session_skip=True，跨交易时段的信号点会被排除（防止节假日后首 bar 被误纳入上周期）
          6. 对于日度倍数频率，按 session 结束时间分组选代表品种，取各组信号索引的并集

        参数：
            freq             : 信号频率 (DataFreq 或可解析字符串)
            end_session_skip : 是否跳过跨 session 的信号点（默认 True）
            end_session_gap  : 判断 session 间隔的最小时间差（默认 3 小时）
            basepoint        : 信号基准点策略：
                                'last'  - 每个周期的最后一根 bar（最常用）
                                'first' - 每个周期的第一根 bar
                                '09:01:00' - 指定时刻的 bar
                                callable - 接收 GroupBy 对象，返回布尔 Series

        返回：
            pd.MultiIndex，名称形如 ['_SIGNAL@{freq}', 'bar_timestamp', ...]
        """
        tester = _active_tester.get()
        if tester is not None:
            products = tester.products
        else:
            raise ValueError("No active tester set in context - _get_sync_signal_index requires an active FactorTester via _active_tester ContextVar.")
        data_dict = {product: product.get_some_data() for product in products}
        assert data_dict, "无法确定交易时间，因为没有产品具有交易数据"

        # 只保留上市时间最早的品种，排除新上市品种对索引造成的偏差
        first_trade_time = {p: data_dict[p].index.get_level_values(-1).date.min() for p in data_dict}  # type: ignore
        min_first_trade_time = min(first_trade_time.values())
        candidates = {p: data_dict[p] for p, t in first_trade_time.items() if t == min_first_trade_time}
        assert candidates, "无法确定最早的交易时间，因为没有产品具有交易数据"

        index_name_stem: str = '_SIGNAL'
        assert freq is not None, "Frequency must be provided"
        freq = DataFreq(freq)

        # 对于日度倍数频率，不同品种收盘时间可能不同（如 15:00 vs 15:15）
        # 按 session 结束时间分组，每组选数据最长的代表品种，取索引并集以覆盖全部 session 类型
        _sample = next(iter(candidates.values()))
        _sample_freqs = [DataFreq(l) for l in _sample.index.names]
        _mult_idx = next((i for i, f in enumerate(_sample_freqs)
                          if freq.value.total_seconds() % f.value.total_seconds() == 0), None)

        if freq.is_day_multiple() and isinstance(basepoint, str) and _mult_idx is not None:
            bp = basepoint.lower()
            _date_col = str(_sample.index.names[_mult_idx])
            is_last = (bp == 'last')
            # 按 mode 收盘/开盘时间分组，每组选数据量最大的代表品种
            time_to_rep: dict = {}
            for p in candidates:
                rows = candidates[p].groupby(_date_col, group_keys=False)
                bars = rows.tail(1) if is_last else rows.head(1)
                mode_t = bars.index.get_level_values(-1).to_series().mode()[0]
                if mode_t not in time_to_rep or len(candidates[p]) > len(candidates[time_to_rep[mode_t]]):
                    time_to_rep[mode_t] = p
            representative_products = list(time_to_rep.values())
        else:
            # 子日频或可调用 basepoint：单一代表品种（数据量最大）
            representative_products = [max(candidates.keys(), key=lambda p: len(candidates[p]))]

        del data_dict

        def _signal_index_for(data: pd.DataFrame) -> pd.Index:
            """为单品种数据构建信号索引（内部辅助函数）。"""
            index_data_freq = [DataFreq(level) for level in data.index.names]
            # 找到 freq 是其整数倍的第一个索引层级
            index_map_of_multiple = [freq.value.total_seconds() % idx_freq.value.total_seconds() == 0 for idx_freq in index_data_freq]
            first_true_idx = next((i for i, is_multiple in enumerate(index_map_of_multiple) if is_multiple), None)
            assert first_true_idx is not None, f"Frequency {freq} is not a multiple of any existing index frequency"
            multiple = int(freq.value.total_seconds() / index_data_freq[first_true_idx].value.total_seconds())
            first_true_series = data.index.get_level_values(str(data.index.names[first_true_idx])).to_series().reset_index(drop=True)

            bp = basepoint
            if isinstance(bp, str):
                bp = bp.lower()
                if bp == 'last':
                    series = data.groupby(str(data.index.names[first_true_idx])).cumcount(ascending=False) == 0
                elif bp == 'first':
                    series = data.groupby(str(data.index.names[first_true_idx])).cumcount() == 0
                else:
                    try:
                        base_time = pd.Timestamp(bp).time()
                        series = data.groupby(str(data.index.names[first_true_idx])).transform(lambda x: pd.DatetimeIndex(x.index.get_level_values(-1)).time == base_time)
                    except Exception:
                        raise ValueError("Invalid basepoint value. Must be 'last', 'first', or a valid time string like '09:01:00'")
            else:
                series = bp(data.groupby(str(data.index.names[first_true_idx])))

            if not any(series):
                series = data.groupby(str(data.index.names[first_true_idx])).cumcount(ascending=False) == 0
            assert isinstance(series, pd.Series) and series.dtype == bool, "basepoint function must return a boolean Series"

            first_true_change_pos = series.reset_index(drop=True).index[series]
            if end_session_skip and freq.value < pd.Timedelta('1day'):
                last_col_series = data.index.get_level_values(str(data.index.names[-1])).to_series().reset_index(drop=True)
                end_session_pos = last_col_series[last_col_series.shift(-1) - last_col_series >= end_session_gap].index
                signal_map_mask = first_true_change_pos.isin({i for start, end in zip([0] + (end_session_pos[:-1].values + 1).tolist(), end_session_pos) for i in range(start + multiple - 1, end + 1, multiple) if start + multiple - 1 <= end})
            else:
                idx = first_true_change_pos.to_series().reset_index(drop=True).index
                signal_map_mask = (idx % multiple == multiple - 1)

            signal_pos = first_true_change_pos[signal_map_mask]
            signal_map = first_true_series.index.isin(signal_pos)
            signal_series = first_true_series.where(signal_map)

            left_indices = data.index.names[:first_true_idx]
            right_indices = data.index.names[first_true_idx+1:]
            index_arrays = [data.index.get_level_values(str(idx)).to_series().where(signal_map) for idx in left_indices] \
                            + [signal_series] \
                            + [data.index.get_level_values(str(idx)).to_series() for idx in right_indices]
            index_names = [str(idx).split('@')[-1] for idx in left_indices] \
                        + [index_name_stem + '@' + freq.name] \
                        + [str(idx).split('@')[-1] for idx in right_indices]
            return pd.MultiIndex.from_arrays(index_arrays, names=index_names).dropna()

        sub_indices = [_signal_index_for(candidates[p]) for p in representative_products]
        result = sub_indices[0]
        for idx in sub_indices[1:]:
            result = result.union(idx)
        return result
    
    def sync_signal(self, data: Any, freq: Any = None,
                    basepoint: 'str|Callable' = 'last',
                    replace_basepoint: 'Optional[str|Callable]' = None,
                    **kwargs) -> pd.Series:
        """
        将原始数据对齐到等间隔信号时间点，是因子时序计算的最后一步。

        核心逻辑：
          - 根据 freq 和 basepoint 构建信号索引（首次调用时计算并缓存）
          - 从 data 中筛选出落在信号索引上的行
          - 可选地用 replace_basepoint 重建索引层（如将 first-bar 索引替换为 last-bar 时间，
            避免因子与收益时间戳对齐错误）

        特殊情况（日度倍数 + basepoint='first'）：
          - 直接从各品种自己的数据取每日第一根 bar（避免不同品种开盘时间差异）
          - 若提供 replace_basepoint，将每日第一 bar 的时间戳替换为对应的 last-bar 时间戳

        参数：
            data             : 原始 pd.DataFrame 或 DataMeta，MultiIndex 行索引
            freq             : 目标信号频率
            basepoint        : 信号基准点（'last'、'first'、时间字符串或 callable）
            replace_basepoint: 替换后的基准点，用于修改输出索引时间戳（可选）

        返回：
            对齐后的 pd.DataFrame 或 pd.Series，索引层名已重命名为 _SIGNAL@{freq}
        """
        if freq is None:
            freq = getattr(self._runtime_ctx, 'signal_freq', pd.Timedelta('1d'))
        freq_dc = DataFreq(freq)
        if isinstance(data, DataMeta):
            data = data.data

        tester = _active_tester.get()
        assert tester is not None, \
            "sync_signal must be called within an active test context (set _active_tester via test() or the server route)"

        # 日度倍数 + first：各品种开盘时间不同，直接用品种自身数据取第一 bar
        if freq_dc.is_day_multiple() and isinstance(basepoint, str) and basepoint.lower() == 'first':
            if replace_basepoint is not None and tester.sync_signal_index_replaced is None:
                with tester._sync_lock:
                    if tester.sync_signal_index_replaced is None:
                        tester.sync_signal_index_replaced = self._get_sync_signal_index(
                            freq_dc, basepoint=replace_basepoint, **kwargs)
            # 找到 freq 对应的日期层级索引位置
            _idx_freqs = [DataFreq(l) for l in data.index.names]
            _mult_idx = next((i for i, f in enumerate(_idx_freqs)
                              if freq_dc.value.total_seconds() % f.value.total_seconds() == 0), None)
            assert _mult_idx is not None, f"Frequency {freq_dc} is not a multiple of any data index frequency"
            _date_col = str(data.index.names[_mult_idx])
            # 每日第一根 bar
            data = data[data.groupby(_date_col).cumcount() == 0].copy()
            # 重命名索引层级以匹配信号命名规范 _SIGNAL@{freq}
            signal_name = '_SIGNAL@' + freq_dc.name
            data.index.names = [signal_name if i == _mult_idx else str(n).split('@')[-1]
                                 for i, n in enumerate(data.index.names)]
            # 将每日 first-bar 时间戳替换为 last-bar 时间戳（保持与收益对齐）
            if tester.sync_signal_index_replaced is not None:
                replaced_idx = tester.sync_signal_index_replaced
                sig_col_r = next(str(n) for n in replaced_idx.names if str(n).startswith('_SIGNAL@'))
                sig_pos_r = list(replaced_idx.names).index(sig_col_r)
                right_cols_r = [str(n) for n in replaced_idx.names[sig_pos_r + 1:]]
                replaced_frame = replaced_idx.to_frame(index=False)
                signal_vals = data.index.get_level_values(signal_name)
                new_arrays = [data.index.get_level_values(n) for n in data.index.names]
                for col in right_cols_r:
                    # 用 pandas Series 保留时区信息
                    mapping = dict(zip(replaced_frame[sig_col_r], replaced_frame[col]))
                    new_arrays[list(data.index.names).index(col)] = pd.DatetimeIndex(
                        [mapping.get(d, pd.NaT) for d in signal_vals])
                data.index = pd.MultiIndex.from_arrays(new_arrays, names=data.index.names)
                # 删除替换时间戳未找到（NaT）的行
                if right_cols_r:
                    data = data[pd.notna(data.index.get_level_values(right_cols_r[0]))]
            return data

        # 标准情况（last、子日频、或可调用 basepoint）
        if tester.sync_signal_index is None:
            with tester._sync_lock:
                if tester.sync_signal_index is None:
                    tester.sync_signal_index = self._get_sync_signal_index(
                        freq_dc, basepoint=basepoint, **kwargs)
        if replace_basepoint is not None and tester.sync_signal_index_replaced is None:
            with tester._sync_lock:
                if tester.sync_signal_index_replaced is None:
                    tester.sync_signal_index_replaced = self._get_sync_signal_index(
                        freq_dc, basepoint=replace_basepoint, **kwargs)
        assert tester.sync_signal_index is not None
        mask = tester.sync_signal_index.isin(data.index)
        # 筛选落在信号索引上的行
        data = data[data.index.isin(tester.sync_signal_index)].copy()
        # 将索引层级名重命名为信号层名（_SIGNAL@{freq}）
        data.index.names = tester.sync_signal_index.names
        # 若有 replace_basepoint，用替换索引覆盖输出索引（改变时间戳）
        if tester.sync_signal_index_replaced is not None:
            index_replaced = tester.sync_signal_index_replaced
            data.index = index_replaced[mask]
        return data

class Returns(FactorFamily):
    """
    内置收益率因子族。

    计算品种在指定频率和价格列下的下期/当期收益率。
    支持 OPEN-to-OPEN 和 CLOSE-to-CLOSE 两种模式。

    参数：
        RF  (Timedelta) : 收益率计算频率，如 '1d'、'1h'
        SC  (DataColumn): 收益起始价格列，默认 CLOSE
        EC  (DataColumn): 收益终止价格列，默认 CLOSE
        S   (int)       : 移位量，1 表示下期收益（shift(-1)），0 表示当期
    """

    params = [
        WindowParam('RF'),  # 收益率计算频率，如 '1d'、'1h'、'30min'
        DataColumnParam('SC', default_value=DataColumn.CLOSE),  # 收益起始列
        DataColumnParam('EC', default_value=DataColumn.CLOSE),  # 收益终止列
        TypeParam('S', default_value=1),  # 移位量：1=下期，0=当期，-1=上期
    ]

    description_sections = [
        {
            'title': '这是什么',
            'body': 'Returns 是系统内置的收益率序列生成因子，用于构造下一期或当期收益，通常作为 IC、分组测试和其他因子评估的目标变量。',
        },
        {
            'title': '它在看什么',
            'body': '它本身不是一个用于预测的 alpha，而是定义“你到底在预测哪个收益口径”。不同的收益频率、收益起点和是否使用下一期收益，会直接改变测试结论。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '严格来说，它不是“为什么有效”的问题，而是“为什么定义准确很重要”。如果目标收益定义错了，再好的预测因子也会被错误地评估。',
        },
        {
            'title': '使用提醒',
            'body': '回测中应优先确认收益频率、对齐方式和是否前视，再比较不同 alpha 的优劣。',
        }
    ]

    def func_timeseries(self, product: Product, RF: pd.Timedelta, SC: DataColumn, EC: DataColumn, S: int, *args, **kwargs) -> pd.Series:
        """
        计算单品种收益率时序。

        当 SC == EC 时（同一价格列）：
          - OPEN 系列：pct_change(RF) + shift(RF*S)，basepoint='first'（开盘对开盘）
          - CLOSE 系列：pct_change(RF) + shift(RF*S)，basepoint='last'（收盘对收盘）
          - 使用 replace_basepoint='last' 将开盘时间戳替换为收盘时间戳以对齐因子

        参数：
            RF : 收益频率
            SC : 起始列（与 EC 相同时生效）
            EC : 终止列
            S  : 移位步数
        """
        data_freq = product.get_current_freq()
        data = getattr(product, data_freq.name)
        assert isinstance(data, DataMeta)
        if SC == EC:
            day_basepoint = 'last'
            if SC in [DataColumn.OPEN, DataColumn.OPEN_ADJUSTED]:
                day_basepoint = 'first'
                ret = data[SC].pct_change(RF).shift(RF*(S-1))
            elif SC in [DataColumn.CLOSE, DataColumn.CLOSE_ADJUSTED]:
                ret = data[SC].pct_change(RF).shift(RF*(S-1))
            else:
                raise ValueError("不支持的价格列，请选择 OPEN、OPEN_ADJUSTED、CLOSE 或 CLOSE_ADJUSTED")
            return self.sync_signal(ret, RF, basepoint=day_basepoint, replace_basepoint='last')
        else:
            raise NotImplementedError("计算不同起止列的收益率尚未实现")
