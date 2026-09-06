from __future__ import annotations

import numpy as np
import pandas as pd

from tools.data.types import DataColumn
from tools.data.types import DataFreq
from tools.factors.FactorExpr import (
    ColumnRef,
    CompositeExpr,
    ConstExpr,
    EvaluateContext,
    FactorExpr,
    ParamRef,
    RollingOp,
    SignalAlign,
    ShiftOp,
    CrossSectionalOp,
    WhereOp,
    get_visual_operator_category,
    get_visual_operator_groups,
    where,
)
from tools.parameters import FactorParam, WindowParam


def _expr(seed: int = 1):
    base = ColumnRef(DataColumn.CLOSE)
    shifted = ShiftOp("shift", ConstExpr(1), base)
    rolled = RollingOp("rolling_mean", ConstExpr(5), shifted)
    return rolled if seed == 1 else CompositeExpr("mul", rolled, ConstExpr(seed))


def test_structural_key_is_stable_for_equivalent_trees():
    assert _expr()._structural_key() == _expr()._structural_key()


def test_structural_key_changes_when_formula_changes():
    assert _expr()._structural_key() != _expr(seed=2)._structural_key()


def test_semantic_fingerprint_is_stable_and_normalizes_symmetric_operands():
    left = ColumnRef(DataColumn.CLOSE)
    right = ColumnRef(DataColumn.OPEN)

    assert (left + right).semantic_fingerprint() == (
        right + left
    ).semantic_fingerprint()
    assert (left - right).semantic_fingerprint() != (
        right - left
    ).semantic_fingerprint()


def test_semantic_fingerprint_distinguishes_array_shape_and_dtype():
    left = ConstExpr(np.array([1, 2], dtype=np.int16))
    reshaped = ConstExpr(np.array([[1, 2]], dtype=np.int16))
    recast = ConstExpr(np.array([1, 2], dtype=np.int32))

    assert left.semantic_fingerprint() != reshaped.semantic_fingerprint()
    assert left.semantic_fingerprint() != recast.semantic_fingerprint()


def test_tree_repr_shows_nested_branch_connectors():
    expr = CompositeExpr(
        "mul",
        CompositeExpr(
            "sub",
            ColumnRef(DataColumn.CLOSE),
            ColumnRef(DataColumn.OPEN),
        ),
        ColumnRef(DataColumn.VOLUME),
    )

    assert expr.tree_repr() == (
        "mul\n"
        "├─ sub\n"
        "│  ├─ ColumnRef[CLOSE]\n"
        "│  └─ ColumnRef[OPEN]\n"
        "└─ ColumnRef[VOLUME]"
    )


def test_to_latex_defines_shared_intermediate_before_dependents():
    shared = (ColumnRef(DataColumn.CLOSE) + ConstExpr(1)).as_intermediate("BASE")
    left = (shared + ConstExpr(2)).as_intermediate("LEFT")
    right = (shared + ConstExpr(3)).as_intermediate("RIGHT")

    latex = (left / right).to_latex()
    lines = latex.splitlines()

    base_line = next(index for index, line in enumerate(lines) if r"\mathrm{BASE}_t &:=" in line)
    left_line = next(index for index, line in enumerate(lines) if r"\mathrm{LEFT}_t &:=" in line)
    right_line = next(index for index, line in enumerate(lines) if r"\mathrm{RIGHT}_t &:=" in line)

    assert base_line < left_line
    assert base_line < right_line
    assert r"\mathrm{BASE}_t + 2" in lines[left_line]
    assert r"\mathrm{BASE}_t + 3" in lines[right_line]


def test_to_latex_does_not_repeat_a_named_root_intermediate():
    expr = (ColumnRef(DataColumn.CLOSE) + ConstExpr(1)).as_intermediate("结果")

    latex = expr.to_latex()

    assert latex.count(":=") == 1
    assert r"\mathrm{结果}_t &:=" in latex
    assert "X_t" not in latex


def test_signal_latex_keeps_return_intermediate_and_colors_only_signal_reverse():
    raw = (ColumnRef(DataColumn.CLOSE) + ConstExpr(1)).as_intermediate()
    aligned = SignalAlign(raw, None)
    latex = aligned.to_latex()
    assert r"\mathrm{I1}_t &:=" in latex
    assert r"\operatorname{Resample}_{\textcolor{red}{\$F}}" in latex
    assert r"\left(\mathrm{I1}_t\right)" in latex
    assert r"\textcolor{red}{-}" in CompositeExpr("neg", aligned).to_latex()
    assert r"\textcolor{red}{-}" not in CompositeExpr("neg", raw).to_latex()


class _FrameExpr(FactorExpr):
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame

    def _structural_key(self):
        return ("FrameExpr",)

    def _evaluate(self, ctx):
        return self.frame

    @property
    def op_name(self):
        return "frame"

    def _to_latex(self, subst=None):
        return "F_t"

    def _get_alias(self):
        return "FRAME"


class _CountingFrameExpr(_FrameExpr):
    calls = 0

    def _evaluate(self, ctx):
        type(self).calls += 1
        return super()._evaluate(ctx)


def test_tanh_public_api_preserves_dataframe_shape_and_metadata():
    values = pd.DataFrame(
        {"A": [-2.0, 0.0, 1.5], "B": [float("nan"), 0.5, 3.0]},
    )

    expr = _FrameExpr(values).tanh()
    result = expr.evaluate(
        ctx=EvaluateContext(products=["A", "B"], freq=DataFreq.MIN1, cache={})
    )

    pd.testing.assert_frame_equal(result, np.tanh(values))
    assert expr._structural_key()[1] == "tanh"
    assert expr.to_latex() == r"\tanh\left(F_t\right)"


def test_batch_cache_reuses_structurally_equal_unmarked_expression():
    values = pd.DataFrame({"A": [1.0, 2.0]})
    left = _CountingFrameExpr(values)
    right = _CountingFrameExpr(values)
    _CountingFrameExpr.calls = 0
    context = EvaluateContext(
        products=["A"], freq=DataFreq.MIN1, cache={},
        shared_cache_keys=frozenset({left._structural_key()}),
    )

    pd.testing.assert_frame_equal(left.evaluate(ctx=context), right.evaluate(ctx=context))

    assert _CountingFrameExpr.calls == 1


def test_where_public_api_matches_direct_node_contract_and_dataframe_semantics():
    values = pd.DataFrame({"A": [1.0, -2.0], "B": [3.0, -4.0]})
    condition = pd.DataFrame({"A": [True, False], "B": [False, True]})

    expr = _FrameExpr(values).where(_FrameExpr(condition), other=-1.0)
    result = expr.evaluate(
        ctx=EvaluateContext(products=["A", "B"], freq=DataFreq.MIN1, cache={})
    )

    expected = values.where(condition, other=-1.0)
    pd.testing.assert_frame_equal(result, expected)
    assert isinstance(expr, WhereOp)

    close = ColumnRef(DataColumn.CLOSE)
    public = close.where(close > 0, other=-1.0)
    direct = WhereOp("where", close > 0, close, ConstExpr(-1.0))
    function_form = where(close > 0, close, -1.0)
    assert public._structural_key() == direct._structural_key()
    assert function_form._structural_key() == direct._structural_key()
    assert public.to_latex() == direct.to_latex()


def test_factor_param_raw_expression_nests_through_tanh_and_where():
    nested = FactorParam("NestedExpression", default_value=None)
    child = ParamRef(nested)
    expr = child.tanh().where(child > 0, other=0.0)

    resolved = expr.resolve(
        param_values={"NestedExpression": ColumnRef(DataColumn.CLOSE)}
    )
    expected = ColumnRef(DataColumn.CLOSE).tanh().where(
        ColumnRef(DataColumn.CLOSE) > 0,
        other=0.0,
    )

    assert resolved._structural_key() == expected._structural_key()
    assert not resolved.param_deps
    assert resolved.supports_incremental()


def test_factor_param_wraps_numeric_constants_as_factor_expressions():
    threshold = FactorParam("NumericFactorConstant", default_value=0.001)

    assert isinstance(threshold.default_value, ConstExpr)
    assert threshold.default_value.value == 0.001

    resolved = ParamRef(threshold).resolve()
    assert isinstance(resolved, ConstExpr)
    assert resolved.value == 0.001

    replacement = threshold._value_space.rectify(2)
    assert isinstance(replacement, ConstExpr)
    assert replacement.value == 2


def test_factor_param_preserves_explicit_signal_alignment():
    aligned = SignalAlign(ColumnRef(DataColumn.CLOSE), "5m")
    nested = FactorParam("AlignedNestedExpression", default_value=aligned)

    assert nested.default_value is aligned
    assert ParamRef(nested).resolve()._structural_key() == aligned._structural_key()


def test_factor_param_alias_preserves_nested_signal_frequency():
    nested = FactorParam(
        "NestedFrequencyAlias",
        default_value="Child|N:2m|$F:5m|$Rev",
    )

    assert nested.get_value_alias(nested.default_value) == "Child|N:2m|$F:5m|$Rev"


def test_authoring_catalog_describes_tanh_without_owning_its_kernel():
    groups = {
        group["key"]: [
            *group.get("operators", []),
            *group.get("more_operators", []),
        ]
        for group in get_visual_operator_groups()
    }

    assert next(item for item in groups["arithUnary"] if item["key"] == "tanh") == {
        "key": "tanh",
        "label": "双曲正切",
        "symbol": "tanh",
        "desc": "X.tanh()",
        "arity": 1,
        "slots": ["序列 X"],
    }
    assert get_visual_operator_category("tanh") == "arithUnary"


def test_timedelta_window_can_drive_dynamic_truncation_offsets():
    window = WindowParam("DynamicTruncWindow", default_value="3m")
    volume = _FrameExpr(pd.DataFrame({"P": [5.0, 4.0, 3.0, 2.0, 1.0]}))
    close = _FrameExpr(pd.DataFrame({"P": [10.0, 11.0, 12.0, 13.0, 14.0]}))
    volume_window = volume.rolling(window)
    peak = volume_window.argmax_raw()
    rise = volume_window.truncate(0, peak - 1).argmin_raw()
    fall = volume_window.truncate(peak + 1, volume_window.bars - 1).argmin_raw()
    rise_close = close.rolling(window).truncate(rise, rise).min()
    fall_close = close.rolling(window).truncate(fall, fall).min()
    expr = (rise_close - fall_close) / (fall - rise + 1e-10)

    resolved = expr.resolve(param_values={"DynamicTruncWindow": pd.Timedelta("3m")})
    result = resolved.evaluate(
        ctx=EvaluateContext(["P"], DataFreq.MIN1, None, {}, None, None)
    )

    assert not result.empty


def test_window_param_numeric_string_is_bar_count_integer():
    window = WindowParam("NumericStringWindow", default_value="10")

    assert window.default_value == 10
    assert window.rectify_value("3") == 3


def test_window_bars_preserves_timedelta_dependency_for_frequency_inference():
    window = WindowParam("FrequencyWindow", default_value="9m")
    volume = _FrameExpr(pd.DataFrame({"P": [1.0]}))
    volume_window = volume.rolling(window)
    expr = volume_window.truncate(0, volume_window.bars - 1).argmin_raw()

    resolved = expr.resolve(param_values={"FrequencyWindow": pd.Timedelta("9m")})

    assert any(ref.value == pd.Timedelta("9m") for ref in resolved.const_refs)


def test_window_latex_keeps_template_parameter_and_formats_resolved_duration():
    window = WindowParam("LatexWindow", default_value="25d")
    volume = _FrameExpr(pd.DataFrame({"P": [1.0]}))
    volume_window = volume.rolling(window)

    template_latex = volume_window.argmax_raw().to_latex()
    template_bars_latex = volume_window.bars.to_latex()
    assert r"\textcolor{red}{LatexWindow}" in template_latex
    assert r"\mathrm{Bars}\left(\textcolor{red}{LatexWindow}\right)" == template_bars_latex

    resolved = volume_window.resolve(
        param_values={"LatexWindow": pd.Timedelta("25d")},
    )
    resolved_latex = resolved.argmax_raw().to_latex()
    resolved_bars_latex = resolved.bars.to_latex()
    assert r"25\,\mathrm{d}" in resolved_latex
    assert r"25\,\mathrm{d}" in resolved_bars_latex
    assert "days" not in resolved_latex
    assert "00:00:00" not in resolved_latex


def test_intermediate_name_collision_is_detectable():
    class MockFactor:
        _intermediate_factor_data = {}
        _intermediate_alias_index = {}

    e1 = _expr().as_intermediate("X")
    e2 = _expr(seed=2).as_intermediate("X")
    factor = MockFactor()
    factor._intermediate_factor_data = {
        e1._structural_key(): pd.DataFrame({"a": [1.0]}),
        e2._structural_key(): pd.DataFrame({"a": [2.0]}),
    }

    factor._intermediate_alias_index["X"] = e1._structural_key()
    existing = factor._intermediate_alias_index["X"]
    assert existing != e2._structural_key()


def test_cs_zscore_maps_constant_cross_section_to_neutral_values():
    values = pd.DataFrame(
        {"A": [1.0, 1.0, float("nan")], "B": [1.0, 2.0, float("nan")], "C": [float("nan"), 3.0, 4.0]},
    )

    result = CrossSectionalOp("cs_zscore", _FrameExpr(values))._apply_op([values])

    assert result.loc[0, "A"] == 0.0
    assert result.loc[0, "B"] == 0.0
    assert pd.isna(result.loc[0, "C"])
    assert result.loc[1].notna().all()
    assert result.loc[2].isna().all()


def test_cs_ordinal_rank_masks_ineligible_products_and_breaks_ties_by_product_key():
    values = pd.DataFrame({"B": [10.0], "A": [10.0], "C": [5.0], "D": [8.0]})
    eligible = pd.DataFrame({"B": [True], "A": [True], "C": [False], "D": [True]})

    result = _FrameExpr(values).cs_ordinal_rank(mask=_FrameExpr(eligible), ascending=False).evaluate(
        ctx=EvaluateContext(products=["B", "A", "C", "D"], freq=DataFreq.MIN1, cache={}),
    )

    expected = pd.DataFrame({"B": [2.0], "A": [1.0], "C": [float("nan")], "D": [3.0]})
    pd.testing.assert_frame_equal(result, expected)


def test_cs_rank_can_rank_only_within_the_eligible_cross_section():
    values = pd.DataFrame({"B": [10.0], "A": [10.0], "C": [5.0], "D": [8.0]})
    eligible = pd.DataFrame({"B": [True], "A": [True], "C": [False], "D": [True]})

    result = _FrameExpr(values).cs_rank(mask=_FrameExpr(eligible)).evaluate(
        ctx=EvaluateContext(products=["B", "A", "C", "D"], freq=DataFreq.MIN1, cache={}),
    )

    expected = pd.DataFrame({"B": [1.0 / 3.0], "A": [1.0 / 3.0], "C": [float("nan")], "D": [-1.0 / 6.0]})
    pd.testing.assert_frame_equal(result, expected)


def test_cs_ordinal_rank_ascending_orders_lowest_eligible_product_first():
    values = pd.DataFrame({"B": [10.0], "A": [10.0], "C": [5.0], "D": [8.0]})
    eligible = pd.DataFrame({"B": [True], "A": [True], "C": [False], "D": [True]})

    result = _FrameExpr(values).cs_ordinal_rank(mask=_FrameExpr(eligible)).evaluate(
        ctx=EvaluateContext(products=["B", "A", "C", "D"], freq=DataFreq.MIN1, cache={}),
    )

    expected = pd.DataFrame({"B": [3.0], "A": [2.0], "C": [float("nan")], "D": [1.0]})
    pd.testing.assert_frame_equal(result, expected)


def test_one_bar_normalized_time_center_is_neutral_on_observed_values():
    values = pd.DataFrame({"A": [4.0, float("nan")], "B": [2.0, 3.0]})

    result = RollingOp("rolling_argmin", ConstExpr(1), _FrameExpr(values)).evaluate(
        ctx=EvaluateContext(products=["A", "B"], freq=DataFreq.MIN1, cache={})
    )

    expected = pd.DataFrame({"A": [0.0, float("nan")], "B": [0.0, 0.0]})
    pd.testing.assert_frame_equal(result, expected)


def test_undefined_constant_cross_section_ic_propagates_as_nan():
    signal = pd.DataFrame({"A": [0.0, 0.0], "B": [0.0, 0.0]})
    returns = pd.DataFrame({"A": [1.0, 2.0], "B": [3.0, 1.0]})

    result = CrossSectionalOp(
        "cs_spearman", _FrameExpr(signal), _FrameExpr(returns),
    ).evaluate(ctx=EvaluateContext(products=["A", "B"], freq=DataFreq.MIN1, cache={}))

    assert result["IC"].isna().all()


def test_cross_section_ic_empty_overlap_preserves_multiindex_shape():
    index = pd.MultiIndex.from_arrays(
        [
            pd.to_datetime(["2024-01-02", "2024-01-03"]),
            pd.to_datetime(["2024-01-02 09:00", "2024-01-03 09:00"]),
        ],
        names=["交易日", "数据源时间"],
    )
    left = pd.DataFrame({"A": [1.0, 2.0]}, index=index)
    right = pd.DataFrame({"B": [3.0, 4.0]}, index=index)

    result = CrossSectionalOp(
        "cs_spearman", _FrameExpr(left), _FrameExpr(right),
    ).evaluate(ctx=EvaluateContext(products=["A", "B"], freq=DataFreq.MIN1, cache={}))

    assert result.empty
    assert isinstance(result.index, pd.MultiIndex)
    assert result.index.names == index.names


def test_cross_section_ic_restores_tuple_intersection_to_multiindex():
    index = pd.MultiIndex.from_arrays(
        [
            pd.to_datetime(["2024-01-02", "2024-01-03"]),
            pd.to_datetime(["2024-01-02 09:00", "2024-01-03 09:00"]),
        ],
        names=["交易日", "数据源时间"],
    )
    left = pd.DataFrame({"A": [1.0, 2.0], "B": [2.0, 1.0]}, index=index)
    right = pd.DataFrame(
        {"A": [2.0, 1.0], "B": [1.0, 2.0]},
        index=pd.Index(list(index)),
    )

    result = CrossSectionalOp(
        "cs_spearman", _FrameExpr(left), _FrameExpr(right),
    ).evaluate(ctx=EvaluateContext(products=["A", "B"], freq=DataFreq.MIN1, cache={}))

    assert isinstance(result.index, pd.MultiIndex)
    assert result.index.names == index.names
