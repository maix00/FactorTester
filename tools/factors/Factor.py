# =============================================================================
# tools/factors/Factor.py
# 因子对象模块
#
# Factor = 已解析的 FactorExpr + 信号对齐参数 + DataFrame 缓存 + 全局唯一标识。
#
# 继承链：FactorExpr → 纯表达式树（运算、求值、LaTeX）
#         UniqueObject → 全局唯一实例（按 alias 复用）
#         Factor → 多重继承两者 = 不含 Parameter 的已绑定表达式 + 数据
#
# Factor 是「不含 Parameter 的 FactorExpr」：
#   - 所有 ParamRef 已由 FactorFamily._resolve_expr_params 解析为 ConstExpr/ColumnRef
#   - 持有 _resolved_expr（纯表达式树）+ signal_freq + is_reversed
#   - calc() 时现场 evaluate → SignalAlign（信号对齐）→ 取反
#   - evaluate() 直接返回 source_table（不走表达式求值，已缓存）
#   - 运算符重载（+, -, *, / 等）来自 FactorExpr，返回 CompositeExpr
#
# 数据存储：
#   - _resolved_expr : 已解析的纯表达式树（无 ParamRef）
#   - source_table   : 表达式求值的原始结果（高频，未对齐）
#   - table          : 信号对齐后的视图
#   - source         : 数据源 DataSource
#   - family         : 创建此 Factor 的 FactorFamily
#   - signal_freq    : 信号频率（对齐目标频率）
#   - is_reversed    : 是否取反
#
# 由 FactorFamily.get_factor() / get_factors() 创建。
# =============================================================================
import numpy as np
import pandas as pd
import uuid
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple, Any, Sequence

from tools import UniqueObject, DataFreq
from tools.products.Product import Product
from tools.factors.FactorExpr import FactorExpr, SignalAlign, signal_align
from tools.factors.FactorData import FactorData
from tools.factors.Parameters import ReturnFreqParam, FactorNextPeriodReturns

if TYPE_CHECKING:
    from tools.factors.FactorFamily import FactorFamily
    from tools.factors.FactorTester import FactorTester
    from tools.data.DataSource import DataSource
    from tools.parameters.Parameter import Parameter
    from tools.factors.FactorExpr import ColumnRef

class Factor(FactorExpr, UniqueObject):
    """
    量化因子 = 已解析的 FactorExpr（无 ParamRef）+ 信号对齐 + DataFrame 缓存。

    继承 FactorExpr → 是一个表达式节点，可参与表达式组合（+, -, cs_rank 等）。
    继承 UniqueObject → 同一 alias 全局唯一实例。

    属性：
        _resolved_expr (FactorExpr)  : 已解析的纯表达式树（无 ParamRef）
        signal_freq    (Any)         : 信号频率（如 '1d', '1h'）
        is_reversed    (bool)        : 是否取反
        source_table   (DataFrame)   : 表达式求值的原始结果（高频，未对齐，CoW）
        table          (DataFrame)   : 信号对齐后的结果（CoW）
        source         (DataSource)  : 数据源（含 freq）
        family         (FactorFamily): 创建此 Factor 的 FactorFamily 实例
        products       (set)         : 参与计算的 Product 集合（从 source_table 列提取）
        freq           (DataFreq)    : 信号频率（从 table 索引的 _SIGNAL@ 层级推断）
        returns        (DataFrame)   : 因子对应的收益率序列（calc_returns 后设置）
        source_data_freq (DataFreq)  : 数据源频率（从 family 继承）
    """

    # 运行时动态属性（calc 后设置）
    source_data_freq: Optional[DataFreq] = None

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
                 _resolved_expr: Optional[FactorExpr] = None,
                 func_expr: Optional[FactorExpr] = None,
                 signal_freq: Any = None,
                 is_reversed: bool = False,
                 family: Optional['FactorFamily'] = None,
                 source: Optional['DataSource'] = None,
                 _local_only: bool = False,
                 **kwargs):
        if not hasattr(self, '_initialized'):
            # FactorExpr 不需要特殊初始化（无 operands）
            FactorExpr.__init__(self)
            UniqueObject.__init__(self, alias=alias, _local_only=_local_only)
            # _resolved_expr: 含 SignalAlign 的完整表达式（求值即对齐）
            # func_expr: 纯因子逻辑（不含 SignalAlign），供外部引用
            # 向后兼容：若有 _resolved_expr 用它，否则用 func_expr
            self._resolved_expr: Optional[FactorExpr] = _resolved_expr or func_expr
            self.signal_freq: Any = signal_freq
            self.is_reversed: bool = is_reversed
            self.family: Optional['FactorFamily'] = family
            self.source: Optional['DataSource'] = source

            # FactorData 引用 + 对齐表（calc 后设置）
            self._factor_data: Optional['FactorData'] = None
            self._aligned_table: Optional[pd.DataFrame] = None
            # 动态属性初始值
            self.source_data_freq: Optional[DataFreq] = None

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
    # 属性：source_table / table
    # ------------------------------------------------------------------

    @property
    def source_table(self) -> pd.DataFrame:
        """表达式求值的原始结果 — 高频，未对齐。"""
        if self._factor_data is not None:
            return self._factor_data.source_table
        return pd.DataFrame()

    @source_table.setter
    def source_table(self, value: pd.DataFrame):
        if self._factor_data is not None:
            self._factor_data.source_table = value

    @property
    def table(self) -> pd.DataFrame:
        """信号对齐后的因子值（pandas 3.0 CoW 零拷贝）。"""
        if self._aligned_table is not None:
            return self._aligned_table
        return pd.DataFrame()

    @table.setter
    def table(self, value: pd.DataFrame):
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
    # 数据频率自动推断
    # ------------------------------------------------------------------

    def _infer_source_freq(self, products: Sequence['Product']) -> DataFreq:
        """
        根据表达式中所有 ConstExpr 的 Timedelta 最小值，自动选择数据源频率。

        规则：
          1. 遍历 _resolved_expr，收集所有 ConstExpr.value 中的 pd.Timedelta
          2. 如果最小窗口 ≥ 1day → DAY1
          3. 如果最小窗口 ≥ 1hour → HOUR1
          4. 否则 → MIN1
          5. 从产品可用频率中选 ≥ 所需频率的最低频（降级兼容）
        """
        from tools.factors.FactorExpr import ConstExpr, FactorExpr

        # Step 1: 遍历表达式树，收集所有 Timedelta 常量
        min_window: Optional[pd.Timedelta] = None
        seen: set[int] = set()
        stack: list[FactorExpr] = [self._resolved_expr]  # type: ignore[list-item]

        def push_operands(expr: FactorExpr):
            for op in getattr(expr, 'operands', []):
                stack.append(op)

        while stack:
            node = stack.pop()
            node_id = id(node)
            if node_id in seen:
                continue
            seen.add(node_id)
            if isinstance(node, ConstExpr):
                val = node.value
                if isinstance(val, pd.Timedelta):
                    if min_window is None or val < min_window:
                        min_window = val
            else:
                push_operands(node)

        # Step 2: 根据最小窗口确定所需最低频率
        if min_window is None or min_window >= pd.Timedelta('1day'):
            desired_freq = DataFreq('DAY1')
        elif min_window >= pd.Timedelta('1hour'):
            desired_freq = DataFreq('HOUR1')
        else:
            desired_freq = DataFreq('MIN1')

        # Step 3: 从产品可用频率中选择合适的最低频
        if products:
            available_freqs = sorted(
                products[0].list_available_freqs(),
                key=lambda f: f.value,
            )
            for af in available_freqs:
                if af.value >= desired_freq.value:
                    return af
            if available_freqs:
                return available_freqs[-1]

        return DataFreq('MIN1')

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
        self._factor_data = None
        self._aligned_table = None

    def calc(self, products: 'Product|List[Product]|Set[Product]',
             source_freq: Optional[DataFreq] = None) -> pd.DataFrame:
        """
        计算因子值。

        流程（SignalAlign + FactorData 架构）：
          1. _resolved_expr.evaluate() → 已对齐的 DataFrame
             _resolved_expr 包含 SignalAlign 节点，求值即对齐
          2. FactorData(expr, raw_result) 去重存储（相同表达式只算一次）
             SignalAlign 的 _structural_key 包含对齐参数 → 不同对齐不同 key
          3. self._aligned_table = result（pandas CoW 零拷贝）
          4. 按 is_reversed 取反
          5. 删除全 NaN 或常数列

        source_freq: 可选，手动指定数据源频率。None 时自动推断。
        """
        if isinstance(products, Product):
            products = [products]
        products = list(products)
        if not products:
            raise ValueError(f"{self}: 无法计算，因为没有提供产品")

        if self._resolved_expr is None:
            raise ValueError(f"{self}: 没有 _resolved_expr，无法计算。"
                             f"请通过 FactorFamily.get_factor() 创建。")
        if self.family is None:
            raise ValueError(f"{self}: 没有关联的 FactorFamily，无法计算。")

        # 数据源频率 —— 外部指定 > 显式配置 > 自动推断
        if source_freq is not None:
            freq = source_freq
        else:
            source_freq_name = getattr(self.family, '_source_freq_name', None)
            if source_freq_name is not None:
                freq = DataFreq(source_freq_name)
            else:
                freq = self._infer_source_freq(products)
        self.source_data_freq = freq

        # ── 预加载：收集需要的列，每个品种只读一次 ──
        from tools.factors.FactorExpr import ColumnRef
        from tools.data.DataMeta import DataMeta

        preloaded: dict = {}
        column_refs = self._resolved_expr.collect_column_refs()
        prod_freq_cols: dict[tuple, set] = {}
        for cr in column_refs:
            col_name = cr.column.name
            for p in products:
                key = (p, freq.name)
                if key not in prod_freq_cols:
                    prod_freq_cols[key] = set()
                prod_freq_cols[key].add(col_name)

        for (p, freq_name), cols in prod_freq_cols.items():
            dm: DataMeta = getattr(p, freq_name)
            if not dm.next_available_source():
                continue
            data = dm.get_and_adjust_cols(list(cols), copy=False)
            if not data.empty:
                preloaded[(p, freq_name)] = data

        # ── 1. 表达式求值 ──
        # _resolved_expr = SignalAlign(func_expr, ...)
        # evaluate 返回已对齐的 DataFrame（SignalAlign._apply_op 对齐）
        # SignalAlign._raw_data 同时保存了未对齐的原始数据
        df_cache: Dict[FactorExpr, pd.DataFrame] = {}
        result = self._resolved_expr.evaluate(
            products, freq, preloaded=preloaded, cache=df_cache)

        # ── 2. FactorData 去重存储（存未对齐的原始数据） ──
        raw_data = self._resolved_expr._raw_data if hasattr(self._resolved_expr, '_raw_data') else result
        self._factor_data = FactorData(self._resolved_expr, raw_data)

        # ── 3. 对齐表（pandas CoW：零拷贝引用） ──
        self._aligned_table = result

        # ── 4. 取反 ──
        if self.is_reversed:
            result = -result
            self._aligned_table = result

        # ── 5. 删除无贡献的列 ──
        col_todrop = [col for col in result.columns
                      if (droppedna := result[col].dropna()).empty
                      or max(droppedna) == min(droppedna)]
        result.drop(columns=col_todrop, inplace=True)
        if result.empty:
            raise ValueError(f"{self}: 计算结果为空，无法计算因子值")

        # ── 6. 同步到 tester 字典（向后兼容 FactorTester 读取） ──
        t = Factor._get_active_tester()
        if t is not None:
            t.factor_source_tables[self] = self._factor_data.source_table
            t.factor_tables[self] = result
        else:
            self._aligned_table = result

        return self.table

    @staticmethod
    def _get_active_tester() -> 'Optional[FactorTester]':
        try:
            from tools.factors.FactorTester import _active_tester
            return _active_tester.get()
        except ImportError:
            return None

    def calc_returns(self, next_return: bool = True, return_freq: Optional[Any] = None,
                     returns_col: FactorNextPeriodReturns = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED) -> pd.DataFrame:
        """
        计算因子对应的收益率序列。

        next_return=True  → 下一期收益（因子用于下期选股）
        next_return=False → 当期收益

        复用主因子的 source_data_freq，确保 Returns 的索引与主因子一致。
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

        # 切换产品当前频率到主因子的数据源频率，确保 Returns 计算一致
        src_freq = self.source_data_freq
        old_freq_map: Dict[Product, Any] = {}
        if src_freq is not None:
            for p in prods:
                try:
                    old_freq_map[p] = p.get_current_freq()
                    if src_freq in p.list_available_freqs():
                        p.set_current_freq(src_freq)
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
            # 复用主因子的 source_freq，避免 Returns 推断出不同频率
            result = return_factor.calc(list(prods), source_freq=src_freq)
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
        # 存入活跃 tester 的 factor_returns，保证后续访问一致性
        if tester is not None:
            tester.factor_returns[self] = result
        return result