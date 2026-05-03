# =============================================================================
# tools/factors/Factor.py
# 因子对象模块
#
# Factor = 已解析的 FactorExpr + DataFrame 缓存 + 全局唯一标识。
#
# 继承链：FactorExpr → 纯表达式树（运算、求值、LaTeX）
#         UniqueObject → 全局唯一实例（按 alias 复用）
#         Factor → 多重继承两者 = 不含 Parameter 的已绑定表达式 + 数据
#
# Factor 是「不含 Parameter 的 FactorExpr」：
#   - 所有 ParamRef 已被 resolve 为 ConstExpr 或 ColumnRef
#   - evaluate() 直接返回 source_table（不走表达式求值，已缓存）
#   - 运算符重载（+, -, *, / 等）来自 FactorExpr，返回 CompositeExpr
#
# 数据存储：
#   - source_table : evaluate() 的原始结果（高频，未对齐）
#   - table        : 信号对齐后的视图
#   - source       : 数据源 DataSource
#   - source_factor: $F=数据源频率 的源 Factor
#   - family       : 创建此 Factor 的 FactorFamily
#
# 由 FactorFamily.get_factor() / get_factors() 创建。
# =============================================================================
import numpy as np
import pandas as pd
import uuid
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Set, Tuple, Any, Sequence

from tools import UniqueObject, DataFreq
from tools.products.Product import Product
from tools.factors.FactorExpr import FactorExpr
from tools.factors.Parameters import ReturnFreqParam, FactorNextPeriodReturns

if TYPE_CHECKING:
    from tools.factors.FactorFamily import FactorFamily
    from tools.factors.FactorTester import FactorTester
    from tools.data.DataSource import DataSource
    from tools.parameters.Parameter import Parameter
    from tools.factors.FactorExpr import ColumnRef


class Factor(FactorExpr, UniqueObject):
    """
    量化因子 = 已解析的 FactorExpr（无 ParamRef）+ DataFrame 缓存。

    继承 FactorExpr → 是一个表达式节点，可参与表达式组合（+, -, cs_rank 等）。
    继承 UniqueObject → 同一 alias 全局唯一实例。

    属性：
        source_table  (DataFrame)   : 表达式求值的原始结果（高频，未对齐）
        table         (DataFrame)   : 信号对齐后的视图
        source        (DataSource)  : 数据源（含 freq）
        source_factor (Factor)      : 数据源频率的源 Factor，None 表示自己就是源
        family        (FactorFamily): 创建此 Factor 的 FactorFamily 实例
        func          (Callable)    : 计算入口（签名 func(products) → aligned table）
        products      (set)         : 参与计算的 Product 集合（从 source_table 列提取）
        freq          (DataFreq)    : 信号频率（从 table 索引的 _SIGNAL@ 层级推断）
    """

    def __new__(cls, alias: Optional[str] = None, *args, family=None,
                _local_only: bool = False, **kwargs):
        # alias 保持纯净（factor_alias），name = {user_prefix}:{core_alias}:{uuid}
        core_alias = alias if alias else cls.__name__
        user_prefix = cls._get_user_prefix(family)
        if user_prefix:
            name = f"{user_prefix}:{core_alias}:{uuid.uuid4().hex}"
        else:
            name = f"{core_alias}:{uuid.uuid4().hex}"
        kwargs.pop('name', None)
        # 直接调用 UniqueObject.__new__（跳过 FactorExpr，它不定义 __new__）
        # search=True: 若已有同名同类 Factor，复用而非新建
        # _local_only=True: 跳过全局注册，仅本地创建（用于中间因子）
        return UniqueObject.__new__(cls, name=name, alias=core_alias, search=True,
                                    _local_only=_local_only, **kwargs)

    def __init__(self, alias: Optional[str] = None,
                 func: Callable[..., pd.DataFrame] = lambda _: pd.DataFrame(),
                 family: Optional['FactorFamily'] = None,
                 source: Optional['DataSource'] = None,
                 **kwargs):
        if not hasattr(self, '_initialized'):
            # FactorExpr 不需要特殊初始化（无 operands）
            FactorExpr.__init__(self)
            UniqueObject.__init__(self, alias=alias)
            self.func = func
            self.family = family
            self.source: Optional[DataSource] = source
            self.source_factor: Optional['Factor'] = None

            # 数据存储
            self._source_table: pd.DataFrame = pd.DataFrame()
            self._aligned_table: pd.DataFrame = pd.DataFrame()

    # ------------------------------------------------------------------
    # FactorExpr 接口实现 —— Factor 作为「已求值的表达式」
    # ------------------------------------------------------------------

    @property
    def op_name(self) -> str:
        """表达式操作名 → Factor 的 alias。"""
        return self.alias

    def to_latex(self) -> str:
        """LaTeX 表达式 → 委托给 family.math_expr 或返回 alias。"""
        if self.family is not None and self.family.math_expr:
            return self.family.math_expr
        return f"\\text{{{self.alias}}}"

    def _get_alias(self) -> str:
        """表达式别名 → Factor 的 alias（用于 CompositeExpr 的 _get_alias）。"""
        return self.alias

    @property
    def dependencies(self) -> Set['FactorExpr']:
        """Factor 是叶子节点，无依赖。"""
        return set()

    @property
    def param_deps(self) -> Set['Parameter']:
        """已解析的 Factor 不含参数引用。"""
        return set()

    def collect_column_refs(self) -> Set['ColumnRef']:
        """已解析的 Factor 不含列引用（求值结果已缓存）。"""
        return set()

    def evaluate(self, products: Sequence['Product'], freq: DataFreq,
                 source: Optional['DataSource'] = None,
                 cache: Optional[Dict['FactorExpr', pd.DataFrame]] = None,
                 preloaded: Optional[Dict[Any, pd.DataFrame]] = None) -> pd.DataFrame:
        """
        因子求值 → 直接返回 source_table（已缓存的求值结果）。

        Factor 是「已求值」的表达式，不需要重新计算。
        如果 cache 中有 self，返回缓存值；否则返回 source_table。
        """
        if cache is not None and self in cache:
            return cache[self]
        result = self.source_table
        if cache is not None:
            cache[self] = result
        return result

    # ------------------------------------------------------------------
    # 属性代理：活跃 FactorTester 时，数据存入 tester 字典（并发安全）
    # ------------------------------------------------------------------

    @staticmethod
    def _get_active_tester() -> 'Optional[FactorTester]':
        try:
            from tools.factors.FactorTester import _active_tester
            return _active_tester.get()
        except ImportError:
            return None

    @property
    def source_table(self) -> pd.DataFrame:
        """表达式求值的原始结果 — 高频，未对齐。"""
        t = self._get_active_tester()
        if t is not None:
            return t.factor_source_tables.get(self, pd.DataFrame())
        return self._source_table

    @source_table.setter
    def source_table(self, value: pd.DataFrame):
        t = self._get_active_tester()
        if t is not None:
            t.factor_source_tables[self] = value
        else:
            self._source_table = value
        # 清除 table 视图缓存
        self._aligned_table = pd.DataFrame()

    @property
    def table(self) -> pd.DataFrame:
        """信号对齐后的因子值。"""
        t = self._get_active_tester()
        if t is not None:
            return t.factor_tables.get(self, pd.DataFrame())
        return self._aligned_table

    @table.setter
    def table(self, value: pd.DataFrame):
        t = self._get_active_tester()
        if t is not None:
            t.factor_tables[self] = value
        else:
            self._aligned_table = value

    @property
    def products(self) -> Set['Product']:
        """参与计算的 Product 集合，从 source_table 的列名提取。"""
        st = self.source_table
        if st.empty:
            return set()
        return {col for col in st.columns if isinstance(col, Product)}

    @property
    def freq(self) -> Optional[DataFreq]:
        """
        信号频率 — 从 table 索引的 _SIGNAL@ 层级推断。
        
        若无 table 数据，返回 None。
        """
        t = self.table
        if t is None or t.empty:
            return None
        idx = t.index
        if isinstance(idx, pd.MultiIndex):
            signal_name = next((n for n in idx.names if n and str(n).startswith('_SIGNAL')), None)
            if signal_name is not None:
                freq_str = str(signal_name).split('@', 1)[-1] if '@' in str(signal_name) else str(signal_name)
                try:
                    return DataFreq(freq_str)
                except Exception:
                    pass
        return None

    @property
    def expr(self) -> 'FactorExpr':
        """Factor 自身就是表达式树 — 返回 self。"""
        return self

    # ------------------------------------------------------------------
    # 用户前缀管理
    # ------------------------------------------------------------------

    @staticmethod
    def _get_user_prefix(family: Optional['FactorFamily'] = None) -> Optional[str]:
        """从 family.name 中提取用户前缀 'username@serial' 或 '$COMMON'。"""
        if family is not None:
            prefix = family._extract_user_prefix()
            if prefix is not None:
                return prefix
        try:
            from tools.factors.FactorTester import _active_user_prefix
            return _active_user_prefix.get()
        except ImportError:
            pass
        return None

    @staticmethod
    def _extract_user_prefix(name: str) -> Tuple[Optional[str], str]:
        """
        从 Factor.name 中分离用户前缀和剩余部分。

        例：'张三@1:MmMABreak|F:1d:a1b2c3d4' → ('张三@1', 'MmMABreak|F:1d:a1b2c3d4')
        """
        if '@' in name:
            parts = name.split(':', 1)
            if len(parts) == 2 and '@' in parts[0] and parts[0].rsplit('@', 1)[-1].isdigit():
                return parts[0], parts[1]
        return None, name

    # ------------------------------------------------------------------
    # 计算生命周期
    # ------------------------------------------------------------------

    def clear(self):
        """清空所有计算结果。"""
        self.source_table = pd.DataFrame()

    def change_current_return_freq(self, return_freq: Any) -> None:
        """更改本 Factor 的收益率计算频率（优先写入活跃 tester）。"""
        t = self._get_active_tester()
        if t is not None:
            t.factor_return_freqs[self] = ReturnFreqParam._value_space.rectify(return_freq)
        else:
            ReturnFreqParam.register(self, return_freq)

    def calc(self, products: 'Product|List[Product]|Set[Product]') -> pd.DataFrame:
        """
        计算因子值。

        流程：
          1. 调用 self.func(products) 获取对齐后的 table
          2. 从 family._last_raw_result 获取高频 source_table
          3. 删除全 NaN 或常数列
        """
        if isinstance(products, Product):
            products = [products]
        products = list(products)
        if not products:
            raise ValueError(f"{self}: 无法计算，因为没有提供产品")

        # 1. func 返回对齐后的 table（family 内部做了 sync + 保存中间因子）
        aligned = self.func(products)
        if aligned.empty:
            raise ValueError(f"{self}: 计算结果为空，请检查func的实现")

        # 2. 从 family 取 sync 前的完整高频数据作为 source_table
        if self.family is not None and hasattr(self.family, '_last_raw_result'):
            raw = self.family._last_raw_result
            if raw is not None and not raw.empty:
                self.source_table = raw

        # 3. 删除无贡献的列
        col_todrop = [col for col in aligned.columns
                      if (droppedna := aligned[col].dropna()).empty
                      or max(droppedna) == min(droppedna)]
        aligned.drop(columns=col_todrop, inplace=True)
        if aligned.empty:
            raise ValueError(f"{self}: 计算结果为空，请检查func的实现")

        self.table = aligned
        return self.table

    def calc_returns(self, next_return: bool = True, return_freq: Optional[Any] = None,
                     returns_col: FactorNextPeriodReturns = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED) -> pd.DataFrame:
        """
        计算因子对应的收益率序列。

        next_return=True  → 下一期收益（因子用于下期选股）
        next_return=False → 当期收益
        """
        if return_freq is not None:
            return_freq = DataFreq(return_freq)
        else:
            f = self.freq
            if f is None:
                raise ValueError(f"{self}: 无法计算收益，频率未设置")
            return_freq = f

        prods = self.products
        if not prods:
            raise ValueError(f"{self}: 无法计算收益，没有产品（请先调用 calc）")

        source_freq = self.source.freq if self.source is not None else None
        old_freq_map: Dict[Product, Any] = {}
        if source_freq is not None:
            for p in prods:
                try:
                    old_freq_map[p] = p.get_current_freq()
                    if source_freq in p.list_available_freqs():
                        p.set_current_freq(source_freq)
                except Exception:
                    pass

        tester = self._get_active_tester()
        start_calc_point = getattr(tester, 'start_calc_point', None)
        from tools.factors.FactorFamily import Returns
        ReturnsFamily = Returns()
        shift = -1 if returns_col.value.name.startswith('OPEN') else 0
        return_factor = ReturnsFamily.get_factor(RF=return_freq.value, SC=returns_col.value,
                                                 S=(shift if next_return else shift + 1))
        try:
            result = return_factor.calc(list(prods))
        finally:
            if old_freq_map:
                for p, f in old_freq_map.items():
                    try:
                        p.set_current_freq(f)
                    except Exception:
                        pass

        result = result.replace([np.inf, -np.inf], np.nan)
        result = result.where(result > -1.0, other=np.nan)
        if start_calc_point is not None and not result.empty:
            idx = pd.DatetimeIndex(result.index.get_level_values(-1))
            ts = pd.Timestamp(start_calc_point)
            if idx.tz is not None:
                if ts.tzinfo is None:
                    ts = ts.tz_localize(idx.tz)
                else:
                    ts = ts.tz_convert(idx.tz)
            else:
                if ts.tzinfo is not None:
                    ts = ts.tz_convert('UTC').tz_localize(None)
            result = result[idx >= ts]
        return result