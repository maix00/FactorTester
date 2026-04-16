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
import pandas as pd
from typing import TYPE_CHECKING, Callable, List, Dict, Optional, Set, Any

from tools import SerialObject, DataFreq
from tools.products.Product import Product
from tools.parameters.Parameter import Parameter
from tools.factors.Parameters import StartCalcPointParam, ReturnFreqParam, FactorNextPeriodReturns

if TYPE_CHECKING:
    from tools.factors.FactorFamily import FactorFamily

class Factor(SerialObject):
    """
    量化因子对象。

    属性：
        func       (Callable)   : 计算因子值的函数，签名 func(products) → DataFrame
        family     (FactorFamily): 创建此 Factor 的 FactorFamily 实例
        params     (list)       : 参数对象列表
        params_dict(dict)       : alias→Parameter 字典
        table      (DataFrame)  : 因子值表，列=Product，索引=信号时间戳 MultiIndex
        products   (set)        : 参与计算的 Product 集合
        returns    (DataFrame)  : 对应下期收益表
        ic_series  (Series)     : IC 时间序列
        ic_stats   (Series)     : IC 统计量（mean/std/IR/t_stat/max/min）
        report     (DataFrame)  : 测试报告（由 FactorFamily.test 写入）
    """

    def __new__(cls, alias: Optional[str] = None, single_use: bool = False, *args, **kwargs):
        # search=True: 若已有同名同类 Factor，复用而非新建
        return super().__new__(cls, type_alias='F', alias=alias, search=True, single_use=single_use)
    
    def __init__(self, alias: Optional[str], func: Callable[..., pd.DataFrame] = lambda _: pd.DataFrame(), 
                 family: Optional['FactorFamily'] = None, param_vals: Optional[Dict[Parameter, Any]] = None,
                 single_use: bool = False):
        if not hasattr(self, '_initialized'):
            super().__init__(type_alias='F', alias=alias, single_use=single_use)
            self.func = func            # 因子计算入口
            self.min_gap: Optional[pd.Timedelta] = None  # 最小时间间隔（计划中功能）
            self.freq: Optional[DataFreq] = None  # 计算后推断的信号频率
            self.family = family        # 创建此 Factor 的 FactorFamily
            
            # 参数注册：优先使用 param_vals 中的键值，否则从 family.params 继承
            if param_vals is None:
                assert self.family is not None, "如果没有提供param_vals参数，则必须提供family参数以从中获取默认参数值"
                self.params = self.family.params
            else:
                param_vals = param_vals if param_vals is not None else {}
                self.params = list(param_vals.keys()) if param_vals is not None else []
                for param in self.params:
                    param.register(self, param_vals[param])
            self.params_dict = {param.alias: param for param in self.params}

            # 计算结果占位符（均为空，compute 后填充）
            self.table: pd.DataFrame = pd.DataFrame()
            self.products: Set[Product] = set()
            self.returns: pd.DataFrame = pd.DataFrame()
            self.ic_series: pd.Series = pd.Series()
            self.ic_stats: pd.Series = pd.Series()
            self.report: pd.DataFrame = pd.DataFrame()

    def clear(self):
        """清空所有计算结果，保留配置信息（func/params/family）。"""
        self.table = pd.DataFrame()
        self.products = set()
        self.returns = pd.DataFrame()
        self.ic_series = pd.Series()
        self.ic_stats = pd.Series()
        self.report = pd.DataFrame()

    def get_current_return_freq(self) -> Any:
        """获取本 Factor 注册的收益率计算频率。"""
        return ReturnFreqParam.get_value(self)
    
    def change_current_return_freq(self, return_freq: Any) -> None:
        """更改本 Factor 的收益率计算频率。"""
        ReturnFreqParam.register(self, return_freq)

    def get_current_start_calc_point(self) -> Any:
        """获取本 Factor 注册的计算起始点（日期或时间戳）。"""
        return StartCalcPointParam.get_value(self)
    
    if TYPE_CHECKING:
        from tools.parameters import DateOrTimeParam
        
    def get_StartCalcPointParam(self) -> 'DateOrTimeParam':
        """返回全局 StartCalcPointParam 单例，供外部查询 isDate 等属性。"""
        return StartCalcPointParam
    
    def change_current_start_calc_point(self, start_calc_point: Any, **kwargs) -> None:
        """更改本 Factor 的计算起始点。"""
        StartCalcPointParam.register(self, start_calc_point, **kwargs)

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
        # 清除 FactorFamily 上缓存的信号同步索引，强制下次重新计算
        if self.family is not None:
            self.family.current_sync_signal_index = None
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
        return self.table
    
    def calc_returns(self, next_return: bool = True, return_freq: Optional[Any] = None,
                     returns_col: FactorNextPeriodReturns = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED) -> pd.DataFrame:
        """
        计算因子对应的收益率序列。

        流程：
          1. 确定收益频率（默认与因子信号频率相同）
          2. 按 returns_col 和 next_return 决定使用哪种价格列及 shift 方向
          3. 临时创建 single_use Returns FactorFamily 实例计算收益
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
        start_calc_point = self.get_current_start_calc_point()
        from tools.factors.FactorFamily import Returns
        # 每次 calc_returns 都创建一个新的临时 Returns 实例（factor_single_use=True），
        # 避免共享 sync_signal 缓存导致数据污染
        ReturnsFamily = Returns(factor_single_use=True)
        StartCalcPointParam.register(ReturnsFamily, start_calc_point)
        ReturnsFamily.products = self.products
        # OPEN 系列收益需提前 shift（下期开盘 = 当期结束后的第一根 bar）
        shift = -1 if returns_col.value.name.startswith('OPEN') else 0
        return_factor = ReturnsFamily.get_factor(RF=return_freq.value, SC=returns_col.value, EC=returns_col.value, S=(shift if next_return else shift + 1))
        StartCalcPointParam.register(return_factor, start_calc_point)
        self.returns = return_factor.calc(self.products)
        return self.returns