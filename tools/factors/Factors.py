from __future__ import annotations

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
import pandas as pd
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple, Union, Any, Sequence

from tools.decorators import factor_workspace
from tools.data.types import DataFreq, UniqueNameObject
from tools.products.Product import Product
from tools.factors.FactorExpr import FactorExpr, SignalAlign, CompositeExpr, build_panel_timeline
from tools.factors.FactorRunResult import FactorRunResult

if TYPE_CHECKING:
    from tools.factors.FactorFamily import FactorFamily
    from tools.factors.FactorTester import FactorTester

@factor_workspace
class Factor(UniqueNameObject, FactorExpr):
    """
    量化因子 = 已解析的 FactorExpr（无 ParamRef）+ 信号对齐 + DataFrame 缓存。

    继承 FactorExpr → 是一个表达式节点，可参与表达式组合（+, -, cs_rank 等）。
    内联去重 → 同 (alias, structural_key) 全局唯一实例（search 模式）。

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
        _source_freq   (DataFreq)    : 数据源频率（从 family 继承）
    """

    ref_prefix = "factor:v2:"

    @classmethod
    def from_frozen_identity(cls, value: object, *, resolver):
        from tools.factors.formula_identity import require_frozen_factor

        frozen = require_frozen_factor(value)
        hydrated = resolver(frozen)
        if not isinstance(hydrated, dict) or not isinstance(
            hydrated.get("expr"), FactorExpr,
        ):
            raise ValueError("Factor resolver must return an expression")
        return cls(
            hydrated["expr"],
            family=hydrated.get("family"),
            frozen_identity=frozen,
        )

    # 运行时动态属性（calc 后设置）
    name: str
    alias: str
    _expr: FactorExpr
    _func_expr: FactorExpr
    _source_expr: FactorExpr
    _freq: Optional[DataFreq] = None
    _source_freq: Optional[DataFreq] = None
    _source_data: Optional[pd.DataFrame] = None  # 未对齐的原始数据 (原 FactorData.source_table)
    _data: Optional[pd.DataFrame] = None          # 信号对齐后的结果
    _intermediate_factor_data: Dict[Tuple, pd.DataFrame]
    _intermediate_alias_index: Dict[str, Tuple]
    family: Optional[FactorFamily] = None

    def supports_incremental(self) -> bool:
        return self._source_expr.supports_incremental()

    def compile_incremental(
        self,
        *,
        factor_alias: str = "factor",
        products: Sequence[Product],
        source_freq: DataFreq | str | None = None,
    ) -> Any:
        return self._source_expr.compile_incremental(
            factor_alias=factor_alias,
            products=products,
            source_freq=source_freq or self._source_freq,
        )

    def clear(self):
        """清空所有计算结果。"""
        self._source_freq = None
        self._source_data = None
        self._data = None
        self._intermediate_factor_data.clear()
        self._intermediate_alias_index.clear()

    def _strip_outer_and_set_freq(self, expr: FactorExpr, preserve_neg: bool, set_freq: bool = False) -> FactorExpr:
        """剥离 $Rev 产生的 neg(SignalAlign(...)) 包装层（不处理因子定义的自然 neg）。

        因子定义的自然最外层 neg 已在 FactorFamily.__new__ 中被剥离，
        此处仅处理 get_factors() 中 is_reversed 产生的 neg(SignalAlign(...)) 包装。
        
        preserve_neg=True  → _func_expr：剥离 SignalAlign，保留 $Rev 的 neg 包裹
        preserve_neg=False → _source_expr：同时剥离 SignalAlign 和 $Rev 的 neg
        """
        if isinstance(expr, SignalAlign):
            if set_freq:
                self._freq = DataFreq(expr.signal_freq)
            return expr.operands[0]
        if (
            isinstance(expr, CompositeExpr)
            and expr.op == 'neg'
            and len(expr.operands) == 1
            and isinstance(expr.operands[0], SignalAlign)
        ):
            if set_freq:
                self._freq = DataFreq(expr.operands[0].signal_freq)
            return expr.operands[0].operands[0] if not preserve_neg else \
                CompositeExpr('neg', expr.operands[0].operands[0])
        return expr

    @staticmethod
    def _get_user_prefix(family: Optional['FactorFamily'] = None) -> Optional[str]:
        """Return explicit owner context without parsing object names."""
        if family is not None:
            return str(getattr(family, 'owner_ref', '') or '') or None
        try:
            from tools.factors.FactorTester import _active_user_prefix
            return _active_user_prefix.get()
        except ImportError:
            pass
        return 'public'

    @factor_workspace
    def __new__(cls, expr: FactorExpr, alias: Optional[str] = None,
                family: Optional[FactorFamily] = None,
                factor_ref: Optional[str] = None,
                owner_ref: Optional[str] = None,
                frozen_identity: Optional[dict] = None,
                *args, **kwargs):
        if expr.param_deps:
            raise ValueError(f"Factor 表达式不能包含未解析的参数引用：{expr.param_deps}")
        if frozen_identity is not None:
            from tools.factors.formula_identity import require_frozen_factor
            frozen_identity = require_frozen_factor(frozen_identity)
            if factor_ref not in {None, "", frozen_identity["ref"]}:
                raise ValueError("factor_ref conflicts with frozen identity")
            factor_ref = frozen_identity["ref"]
            alias = frozen_identity["alias"]
            owner_ref = frozen_identity["owner_ref"]
        core_alias = alias or cls.__name__
        selected_owner = str(owner_ref or cls._get_user_prefix(family) or "public")
        if factor_ref:
            name = str(factor_ref)
        elif selected_owner:
            name = (
                f"runtime-factor:{selected_owner}:{core_alias}:"
                f"{expr.semantic_fingerprint()}"
            )
        else:
            name = f"runtime-factor:{core_alias}:{expr.semantic_fingerprint()}"
        name = kwargs.pop('name', name)
        alias = kwargs.pop('alias', core_alias)

        # 去重由 UniqueNameObject.__new__ 按 name 完成
        instance = UniqueNameObject.__new__(
            cls, name=name, alias=alias, frozen_identity=frozen_identity,
        )

        if not hasattr(instance, '_initialized'):
            instance._expr = expr
            instance._func_expr = instance._strip_outer_and_set_freq(expr, preserve_neg=True, set_freq=True)
            instance._source_expr = instance._strip_outer_and_set_freq(expr, preserve_neg=False)
            instance.family = family
            instance.factor_ref = str(factor_ref or "")
            instance.owner_ref = selected_owner
            instance._intermediate_factor_data = {}
            instance._intermediate_alias_index = {}
            super(FactorExpr, instance).__init__()
        return instance
    
    # __eq__/__hash__ 继承自 UniqueNameObject（按 name 比较/哈希）。
    # 显式覆盖是为了阻断 FactorExpr.__eq__（返回 CompositeExpr 会破坏 dict key 协议）。
    # UniqueNameObject 已提供正确行为，无需额外 bridge。

    def _structural_key(self) -> tuple:
        """代理到内部已解析表达式树的结构键（IC 测试需要）。"""
        return self._expr._structural_key()

    def __getattr__(self, item):
        # 内部属性不可代理，避免 __new__ 中 hasattr() 调用触发的无限递归
        # __eq__/__hash__ 不可代理 — FactorExpr.__eq__ 返回 CompositeExpr 破坏 dict key 协议
        if item in ('_expr', '_initialized', '_func_expr', '_source_expr', '_data',
                     '_source_data', '__eq__', '__hash__'):
            raise AttributeError(item)
        return getattr(self._expr, item)

    def evaluate(self, products: Sequence['Product']|set['Product'],
                 freq: Optional[DataFreq] = None, *args,
                 start_dt: Any = None, end_dt: Any = None,
                 warmup_window: Any = None, **kwargs) -> pd.DataFrame:
        """
        计算因子值。

        流程（SignalAlign + FactorData 架构）：
          1. _expr.evaluate() → 已对齐（且可能取反）的 DataFrame
             _expr = neg(SignalAlign(func_expr, ...)) 或 SignalAlign(func_expr, ...)
             取反已内化到表达式层 → pos/neg 因子有不同 structural key
          2. FactorData(expr, raw_result) 去重存储（相同表达式只算一次）
             SignalAlign 的 _structural_key 包含对齐参数 → 不同对齐不同 key
             neg() 包裹 → pos/neg 不同 key
          3. self._aligned_table = result（pandas CoW 零拷贝）
          4. 保留常数或全 NaN 列，由测试消费层表达“无信息”结果

        freq: 可选，手动指定数据源频率。None 时自动推断。
        """
        evaluation_context = kwargs.pop('_evaluation_context', None)
        if isinstance(products, Product):
            products = [products]
        products = list(products)
        if not products:
            raise ValueError(f"{self}: 无法计算，因为没有提供产品")

        if self._expr is None:
            raise ValueError(f"{self}: 没有 _expr，无法计算。"
                             f"请通过 FactorFamily.get_factor() 创建。")
        if self.family is None:
            raise ValueError(f"{self}: 没有关联的 FactorFamily，无法计算。")

        from tools.factors.evaluation.source_frequency import resolve_source_frequency
        freq = resolve_source_frequency(self, products, freq)

        requested_products = list(products)
        freq_name = freq.name
        products = [
            product
            for product in requested_products
            if any(getattr(available, 'name', str(available)) == freq_name
                   for available in product.list_available_freqs())
        ]
        if not products:
            available_sample = {
                str(getattr(product, 'name', product)): [
                    f"{getattr(available, 'name', str(available))}<{type(available).__module__}.{type(available).__name__}>"
                    for available in product.list_available_freqs()
                ]
                for product in requested_products[:5]
            }
            raise ValueError(
                f"{self}: 没有产品提供数据频率 {freq_name}，无法计算因子值；"
                f"requested_type={type(freq).__module__}.{type(freq).__name__}, "
                f"available_sample={available_sample}"
            )
        self._source_freq = freq

        # ── 运行窗口：调用方必须显式提供 start_dt，不能再从 tester/参数隐式回退 ──
        if start_dt is None:
            raise ValueError(f"{self}: factor.evaluate() requires explicit start_dt")
        _tester = Factor._get_active_tester()

        if evaluation_context is not None:
            evaluation_context.assert_compatible(
                products=products, freq=freq, start_dt=start_dt,
                end_dt=end_dt, warmup_window=warmup_window,
            )
            preloaded = evaluation_context.preloaded
            panel_timeline = evaluation_context.panel_timeline
            shared_cache_keys = evaluation_context.shared_cache_keys
        else:
            # ── 预加载：收集需要的列，每个品种只读一次 ──
            from tools.data.views.ProductDataView import ProductDataView

            preloaded: dict = {}
            column_refs = self._expr.column_refs
            columns = list(cr.column.name for cr in column_refs)
            if columns:
                for p in products:
                    dm: ProductDataView = getattr(p, freq.name)
                    data = dm.get_and_adjust_cols(
                        columns,
                        copy=False,
                        start_dt=start_dt,
                        end_dt=end_dt,
                        warmup_window=warmup_window,
                    )
                    if not data.empty:
                        preloaded[(p, freq.name)] = data
            panel_timeline = build_panel_timeline(products, freq, preloaded)
            shared_cache_keys = None

        # ── 获取/创建 FactorRunResult；选择缓存目标 ──
        # 有 tester → 局部 dict（每次 evaluate() 调用独立，不跨 tester 污染）
        # 无 tester → 回退到 _intermediate_factor_data（仅用于独立 Factor，如 CrossSectionIC）
        if _tester is not None:
            r = _tester._get_result(self)
            _intermediate_cache = (
                evaluation_context.shared_cache if evaluation_context is not None else {}
            )
        else:
            r = FactorRunResult(factor=self)
            # A Factor instance is interned by alias/name and can therefore be
            # reused by more than one backtest in the long-lived worker.  The
            # old implementation used ``_intermediate_factor_data`` itself as
            # the expression cache.  Its keys only describe expression
            # structure, not products, source revision, or run window, so a
            # later run could silently reuse the previous run's DataFrame (for
            # example a Jan--Mar table for a Jan--Jun request).  Keep the
            # user-facing intermediate result, but make the actual evaluation
            # cache run-local and discard the previous snapshot before each
            # independent evaluation.
            self._intermediate_factor_data.clear()
            self._intermediate_alias_index.clear()
            _intermediate_cache = {}

        # ── 1. 表达式求值 ──
        # _expr = neg(SignalAlign(func_expr, ...)) 或 SignalAlign(func_expr, ...)
        # evaluate 先递归求值 SignalAlign（对齐），再取反（如有 neg 包裹）
        # SignalAlign._raw_data 同时保存了未对齐的原始数据
        result = self._expr.evaluate(products=products, freq=freq, preloaded=preloaded,
                                     cache=_intermediate_cache, start_dt=start_dt,
                                     end_dt=end_dt,
                                     warmup_window=warmup_window,
                                     run_result=r if _tester is not None else None,
                                     panel_timeline=panel_timeline,
                                     shared_cache_keys=shared_cache_keys)

        # ── 2. 提取未对齐的原始数据 ──
        # 穿透 neg 层找到 SignalAlign，获取其 _raw_data
        raw_data: pd.DataFrame = result  # fallback
        node = self._expr
        while True:
            if isinstance(node, SignalAlign):
                raw_data = node._raw_data  # type: ignore[assignment]
                break
            # CompositeExpr('neg', ...) → 穿透
            operands = getattr(node, 'operands', None) or getattr(node, '_operands', None)
            if operands and len(operands) == 1:
                node = operands[0]
            else:
                break

        # ── 3. 保留无信息信号 ──
        # 常数信号是合法的研究结果；其 IC 应为 NaN，而不是因列被删除导致求值失败。
        # 全 NaN 信号同样交由 IC/分组测试层决定如何呈现或提示。
        if result.empty:
            raise ValueError(f"{self}: 计算结果为空，无法计算因子值")

        # ── 4. 全部数据写入 FactorRunResult（per-tester 隔离）──
        if _tester is not None:
            r = _tester._get_result(self)
            r.source_table = raw_data
            r.table = result
            r.panel_timeline = panel_timeline
        else:
            # 无 tester（如 CrossSectionIC 独立 evaluate）：写入 Factor 本地缓存
            self._source_data = raw_data
            self._data = result

        # ── 5. 收集中间因子别名索引 ──
        self._collect_intermediates_from_cache(_intermediate_cache)

        return result
    
    def _collect_intermediates_from_cache(self, cache: Optional[dict] = None) -> None:
        """遍历表达式树，将中间缓存中的 sk 映射到别名。

        cache: 表达式求值缓存（有 tester 时为局部 dict，无 tester 时为 _intermediate_factor_data）。
        """
        if cache is None:
            return
        self._intermediate_alias_index.clear()

        for node in self._expr.iter_intermediate_nodes():
            name = node._intermediate_name
            sk = node._structural_key()
            if name and sk in cache:
                existing_sk = self._intermediate_alias_index.get(name)
                if existing_sk is not None and existing_sk != sk:
                    raise ValueError(
                        f"中间因子名称冲突：'{name}' 已被 structural_key={existing_sk} 注册，"
                        f"不能再用 structural_key={sk} 注册。"
                        f"每个 as_intermediate(name) 必须对应唯一表达式结构。"
                    )
                self._intermediate_alias_index[name] = sk
                # 将局部 cache 中的数据同步到 _intermediate_factor_data，
                # 使 get_intermediate() 在有 tester 时也能查到 intermediate 数据
                self._intermediate_factor_data[sk] = cache[sk]
    
    @factor_workspace
    def get_intermediate(self, key: Union[str, Tuple]) -> Optional[pd.DataFrame]:
        """
        获取中间因子数据（原始未对齐 DataFrame）。

        无 tester 时从 _intermediate_factor_data 获取（如 CrossSectionIC 独立 evaluate）。
        有 tester 时：用 _func_expr 对 FactorRunResult.func_table 做 SignalAlign 对齐。

        key 支持两种形式：
          - str: 按 .as_intermediate() 注册的名称查找，如 'FE', 'RE'
          - Tuple (structural_key): 按表达式结构 key 直接查找
        """
        if isinstance(key, str):
            sk = self._intermediate_alias_index.get(key)
            if sk is None:
                return None
        else:
            sk = key
        result = self._intermediate_factor_data.get(sk)
        if isinstance(result, dict):
            return pd.DataFrame(result)
        return result
    
    @property
    @factor_workspace
    def freq(self) -> DataFreq:
        if self._freq is not None:
            return self._freq
        t = self.table
        if t is None or t.empty:
            raise ValueError(f"{self}: 因子频率未能推断")
        idx = t.index
        if isinstance(idx, pd.MultiIndex):
            signal_name = next((n for n in idx.names if n and str(n).startswith('_SIGNAL')), None)
            if signal_name is not None:
                freq_str = str(signal_name).split('@', 1)[-1] if '@' in str(signal_name) else str(signal_name)
                try:
                    return DataFreq(freq_str)
                except Exception:
                    pass
        raise ValueError(f"{self}: 因子频率未能推断")
    
    @property
    @factor_workspace
    def source_table(self) -> pd.DataFrame:
        tester = self._get_active_tester()
        if tester is not None:
            r = tester.results.get(self) if hasattr(tester, 'results') else None
            if r is not None and hasattr(r, 'source_table') and not r.source_table.empty:
                return r.source_table
        if self._source_data is not None:
            return self._source_data
        return pd.DataFrame()

    @property
    @factor_workspace
    def table(self) -> pd.DataFrame:
        tester = self._get_active_tester()
        if tester is not None:
            r = tester.results.get(self) if hasattr(tester, 'results') else None
            if r is not None and not r.table.empty:
                return r.table
        if self._data is not None:
            return self._data
        return pd.DataFrame()

    @table.setter
    @factor_workspace
    def table(self, value: pd.DataFrame):
        self._data = value

    @property
    @factor_workspace
    def products(self) -> Set['Product']:
        """参与计算的 Product 集合，从 source_table 的列名提取。"""
        st = self.source_table
        if st.empty:
            return set()
        return {col for col in st.columns if isinstance(col, Product)}

    @property
    @factor_workspace
    def expr(self) -> 'FactorExpr':
        return self._expr

    @staticmethod
    def _get_active_tester() -> 'Optional[FactorTester]':
        try:
            from tools.factors.FactorTester import _active_tester
            return _active_tester.get()
        except ImportError:
            return None
