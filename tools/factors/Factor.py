# =============================================================================
# tools/factors/Factor.py
# 因子对象模块
#
# Factor 代表一个完整的量化因子，包含：
#   - func : 计算函数（通常由 FactorFamily.func 的 partial 包装提供）
#   - table: 因子值 DataFrame，列为 Product, 索引为信号时间戳的 MultiIndex
#   - returns: 对应的下期收益 DataFrame
#   - ic_series / ic_stats: IC 序列及统计量
#
# Factor 是不可变值对象：同一 alias 对应同一个实例（search=True 创建模式）。
# 由 FactorFamily.get_factor() / get_factors() 创建，不应直接实例化。
# =============================================================================
import numpy as np
import pandas as pd
import uuid
from typing import TYPE_CHECKING, Callable, List, Dict, Optional, Set, Any, Tuple

from tools import UniqueObject, DataFreq
from tools.parameters import Parameter
from tools.products.Product import Product
from tools.parameters.Parameter import Parameter
from tools.factors.Parameters import ReturnFreqParam, FactorNextPeriodReturns

if TYPE_CHECKING:
    from tools.factors.FactorFamily import FactorFamily

class Factor(UniqueObject):
    """
    量化因子对象。

    属性：
        func       (Callable)    : 计算因子值的函数，签名 func(products) → DataFrame
        family     (FactorFamily): 创建此 Factor 的 FactorFamily 实例
        params     (list)        : 参数对象列表
        params_dict(dict)        : alias→Parameter 字典
        table      (DataFrame)   : 因子值表，列=Product，索引=信号时间戳 MultiIndex
        products   (set)         : 参与计算的 Product 集合
        returns    (DataFrame)   : 对应下期收益表
        ic_series  (Series)      : IC 时间序列
        ic_stats   (Series)      : IC 统计量（mean/std/IR/t_stat/max/min）
        report     (DataFrame)   : 测试报告（由 FactorFamily.test 写入）
    """

    def __new__(cls, alias: Optional[str] = None, *args, family=None, **kwargs):
        # alias 保持纯净（factor_alias），name = {user_prefix}:{core_alias}:{uuid}
        core_alias = alias if alias else cls.__name__
        user_prefix = cls._get_user_prefix(family)
        if user_prefix:
            name = f"{user_prefix}:{core_alias}:{uuid.uuid4().hex}"
        else:
            name = f"{core_alias}:{uuid.uuid4().hex}"
        # 移除 kwargs 中的 name（避免与 __new__ 自动生成的 name 冲突）
        kwargs.pop('name', None)
        # search=True: 若已有同名同类 Factor，复用而非新建
        return super().__new__(cls, name=name, alias=core_alias, search=True, **kwargs)
    
    def __init__(self, alias: Optional[str] = None, func: Callable[..., pd.DataFrame] = lambda _: pd.DataFrame(), 
                 family: Optional['FactorFamily'] = None, param_vals: Optional[Dict[Parameter, Any]] = None,
                 **kwargs):
        if not hasattr(self, '_initialized'):
            super().__init__(alias=alias)
            self.func = func            # 因子计算入口
            self.min_gap: Optional[pd.Timedelta] = None  # 最小时间间隔（计划中功能）
            self.freq: Optional[DataFreq] = None  # 计算后推断的信号频率
            self.family = family        # 创建此 Factor 的 FactorFamily
            
            # 参数注册：
            #   $开头的参数 → 全局共享单例，直接注册
            #   非$开头的参数 → 创建家族级共享副本，name = {alias}:{family.name}
            if param_vals is None:
                assert self.family is not None, "如果没有提供param_vals参数，则必须提供family参数以从中获取默认参数值"
                self.params = []
                for param in self.family.params:
                    if param.alias.startswith('$'):
                        p = param
                    else:
                        clone_name = f"{param.alias}:{self.family.name}"
                        p = Parameter(name=clone_name, alias=param.alias,
                                      value_space=param._value_space,
                                      default_value=param.default_value)
                    p.register(self, p.default_value)
                    self.params.append(p)
            else:
                self.params = []
                for param, value in param_vals.items():
                    if param.alias.startswith('$'):
                        p = param
                    else:
                        assert self.family is not None, "param_vals 中非$参数需要 family 来生成 clone_name"
                        clone_name = f"{param.alias}:{self.family.name}"
                        p = Parameter(name=clone_name, alias=param.alias,
                                      value_space=param._value_space,
                                      default_value=param.default_value)
                    p.register(self, value)
                    self.params.append(p)
                    param.register(self, value)
            self.params_dict = {param.alias: param for param in self.params}

            self.products: Set[Product] = set()
            self.source_data_freq: Optional[DataFreq] = None  # 因子计算实际使用的数据源频率（如 MIN1 / DAY1）
            # 计算结果的实例级回退（无活跃 FactorTester 时使用，例如独立脚本场景）
            self._table: pd.DataFrame = pd.DataFrame()
            self._returns: pd.DataFrame = pd.DataFrame()
            self._ic_series: pd.Series = pd.Series()
            self._ic_stats: pd.Series = pd.Series()
            self._report: pd.DataFrame = pd.DataFrame()

    # ------------------------------------------------------------------
    # 属性代理：当有活跃 FactorTester（通过 ContextVar 注入）时，
    # 所有可变计算结果存入 tester 的 per-factor 字典，实现并发安全隔离。
    # 无 tester 时（单机脚本场景）回退到实例私有属性。
    # ------------------------------------------------------------------

    @staticmethod
    def _get_active_tester():
        try:
            from tools.factors.FactorFamily import _active_tester
            return _active_tester.get()
        except ImportError:
            return None

    @property
    def table(self) -> pd.DataFrame:
        t = self._get_active_tester()
        if t is not None:
            return t.factor_tables.get(self, pd.DataFrame())
        return self._table

    @table.setter
    def table(self, value: pd.DataFrame):
        t = self._get_active_tester()
        if t is not None:
            t.factor_tables[self] = value
        else:
            self._table = value

    @property
    def returns(self) -> pd.DataFrame:
        t = self._get_active_tester()
        if t is not None:
            return t.factor_returns.get(self, pd.DataFrame())
        return self._returns

    @returns.setter
    def returns(self, value: pd.DataFrame):
        t = self._get_active_tester()
        if t is not None:
            t.factor_returns[self] = value
        else:
            self._returns = value

    @property
    def ic_series(self) -> pd.Series:
        t = self._get_active_tester()
        if t is not None:
            return t.factor_ic_series.get(self, pd.Series())
        return self._ic_series

    @ic_series.setter
    def ic_series(self, value: pd.Series):
        t = self._get_active_tester()
        if t is not None:
            t.factor_ic_series[self] = value
        else:
            self._ic_series = value

    @property
    def ic_stats(self) -> pd.Series:
        t = self._get_active_tester()
        if t is not None:
            return t.factor_ic_stats.get(self, pd.Series())
        return self._ic_stats

    @ic_stats.setter
    def ic_stats(self, value: pd.Series):
        t = self._get_active_tester()
        if t is not None:
            t.factor_ic_stats[self] = value
        else:
            self._ic_stats = value

    @property
    def report(self) -> pd.DataFrame:
        t = self._get_active_tester()
        if t is not None:
            return t.factor_reports.get(self, pd.DataFrame())
        return self._report

    @report.setter
    def report(self, value: pd.DataFrame):
        t = self._get_active_tester()
        if t is not None:
            t.factor_reports[self] = value
        else:
            self._report = value

    # ------------------------------------------------------------------
    # 用户前缀管理：Factor.name = {user_prefix}:{factor_alias}:{uuid}
    # 格式：'username@serial:family_alias|params:uuid'
    # ------------------------------------------------------------------

    @staticmethod
    def _get_user_prefix(family: Optional['FactorFamily'] = None) -> Optional[str]:
        """从 family.name 中提取用户前缀 'username@serial' 或 '$COMMON'，无 family 时从 ContextVar 获取。"""
        if family is not None:
            prefix = family._extract_user_prefix()
            if prefix is not None:
                return prefix
        try:
            from tools.factors.FactorFamily import _active_user_prefix
            return _active_user_prefix.get()
        except ImportError:
            pass
        return None

    @staticmethod
    def _extract_user_prefix(name: str) -> Tuple[Optional[str], str]:
        """
        从 Factor.name 中分离用户前缀和剩余部分。

        例：'张三@1:MmMABreak|F:1d:a1b2c3d4' → ('张三@1', 'MmMABreak|F:1d:a1b2c3d4')
        若无用户前缀：'MmMABreak|F:1d:a1b2c3d4' → (None, 'MmMABreak|F:1d:a1b2c3d4')
        """
        if '@' in name:
            parts = name.split(':', 1)
            if len(parts) == 2 and '@' in parts[0] and parts[0].rsplit('@', 1)[-1].isdigit():
                return parts[0], parts[1]
        return None, name

    def clear(self):
        """清空所有计算结果，保留配置信息（func/params/family）。"""
        self.table = pd.DataFrame()
        self.products = set()
        self.source_data_freq = None
        self.returns = pd.DataFrame()
        self.ic_series = pd.Series()
        self.ic_stats = pd.Series()
        self.report = pd.DataFrame()

    def change_current_return_freq(self, return_freq: Any) -> None:
        """更改本 Factor 的收益率计算频率（优先写入活跃 tester）。"""
        t = self._get_active_tester()
        if t is not None:
            t.factor_return_freqs[self] = ReturnFreqParam._value_space.rectify(return_freq)
        else:
            ReturnFreqParam.register(self, return_freq)

    def _set_products(self):
        """从 table 列中提取 Product 实例集合，写入 self.products。"""
        self.products = set([col for col in self.table.columns if isinstance(col, Product)])

    def get_freq(self, infer: bool = False) -> DataFreq:
        """
        获取因子信号频率。

        infer=False（默认）：从 table 索引列名中提取以 '_SIGNAL' 开头的层级，解析其 DataFreq。
        infer=True：从最细粒度索引列的差分 mode 值推断频率（较慢，用于验证）。
        """
        if self.table.empty:
            raise ValueError(f"{self}: 无法获取频率，因为表格为空")
        if infer:
            # 从时间戳差分推断，可能受交易日空洞影响
            idx_lvls = len(self.table.index.names)
            series = self.table.index.get_level_values(idx_lvls-1).to_series()
            series = pd.to_datetime(series, errors='coerce').sort_values()
            return DataFreq(series.diff().dropna().mode()[0])
        else:
            # 从 _SIGNAL@{freq} 格式的索引列名直接解析
            signal_index = next((str(name) for name in self.table.index.names if name and str(name).startswith('_SIGNAL')), None)
            if signal_index is None:
                raise ValueError(f"{self}: 无法获取频率，因为没有找到以'_SIGNAL'开头的索引列")
            return DataFreq(signal_index)

    def calc(self, products: 'Product|List[Product]|Set[Product]') -> pd.DataFrame:
        """
        计算因子值。

        调用 self.func(products) 获取 DataFrame，
        并自动：清除缓存索引（令 FactorFamily 重新构建信号同步索引）、
        删除全 NaN 或常数列（无信息量的品种）、
        写入 products 和 freq。
        """
        if isinstance(products, Product):
            products = [products]
        products = list(products)
        if not products:
            raise ValueError(f"{self}: 无法计算，因为没有提供产品")
        # sync_signal 索引缓存被清除在 FactorFamily.func() 里（通过 tester.sync_signal_index = None）
        self.table = self.func(products)
        if self.table.empty:
            raise ValueError(f"{self}: 计算结果为空，请检查func的实现")
        # 删除全 NaN 或常数列（对因子无贡献的品种）
        col_todrop = [col for col in self.table.columns if (droppedna := self.table[col].dropna()).empty or max(droppedna) == min(droppedna)]
        self.table.drop(columns=col_todrop, inplace=True)
        if self.table.empty:
            raise ValueError(f"{self}: 计算结果为空，请检查func的实现")
        self._set_products()
        self.freq = self.get_freq()
        if self.family is not None:
            self.source_data_freq = getattr(self.family, '_last_source_data_freq', None)
        return self.table
    
    def calc_returns(self, next_return: bool = True, return_freq: Optional[Any] = None,
                     returns_col: FactorNextPeriodReturns = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED) -> pd.DataFrame:
        """
        计算因子对应的收益率序列。

        流程：
          1. 确定收益频率（默认与因子信号频率相同）
          2. 按 returns_col 和 next_return 决定使用哪种价格列及 shift 方向
          3. 通过 Returns FactorFamily 实例计算收益
          4. 结果写入 self.returns 并返回

        next_return=True  → 下一期收益（因子用于下期选股）
        next_return=False → 当期收益
        """
        if return_freq is not None:
            return_freq = DataFreq(return_freq)
        else:
            if self.freq is None:
                self.freq = self.get_freq()
            return_freq = self.freq
        if self.products is None or not self.products:
            self._set_products()
        assert self.freq is not None, f"{self}: 无法计算收益，因为频率未设置，请先调用calc方法计算因子值以设置频率，或者手动设置频率后再调用本方法"
        # 优先使用因子计算时记录的数据源频率，确保 returns 与因子时序来源一致。
        source_freq = self.source_data_freq
        old_freq_map: Dict[Product, Any] = {}
        if source_freq is not None and self.products:
            for p in self.products:
                try:
                    old_freq_map[p] = p.get_current_freq()
                    if source_freq in p.list_available_freqs():
                        p.set_current_freq(source_freq)
                except Exception:
                    pass
        # 从活跃 FactorTester 获取带时区的起始时间
        tester = self._get_active_tester()
        start_calc_point = getattr(tester, 'start_calc_point', None)
        from tools.factors.FactorFamily import Returns
        ReturnsFamily = Returns()
        # OPEN 系列收益需提前 shift（下期开盘 = 当期结束后的第一根 bar）
        shift = -1 if returns_col.value.name.startswith('OPEN') else 0
        return_factor = ReturnsFamily.get_factor(RF=return_freq.value, SC=returns_col.value, S=(shift if next_return else shift + 1))
        try:
            self.returns = return_factor.calc(self.products)
        finally:
            if old_freq_map:
                for p, f in old_freq_map.items():
                    try:
                        p.set_current_freq(f)
                    except Exception:
                        pass
        # pct_change(价格为0) → inf 或 -1（次期价格为0），均视为无意义数据，替换为 NaN
        self.returns = self.returns.replace([np.inf, -np.inf], np.nan)
        self.returns = self.returns.where(self.returns > -1.0, other=np.nan)
        # 用 start_calc_point 截断收益表（带时区对齐）
        if start_calc_point is not None and not self.returns.empty:
            idx = pd.DatetimeIndex(self.returns.index.get_level_values(-1))
            ts = pd.Timestamp(start_calc_point)
            if idx.tz is not None:
                if ts.tzinfo is None:
                    ts = ts.tz_localize(idx.tz)
                else:
                    ts = ts.tz_convert(idx.tz)
            else:
                if ts.tzinfo is not None:
                    ts = ts.tz_convert('UTC').tz_localize(None)
            self.returns = self.returns[idx >= ts]
        return self.returns