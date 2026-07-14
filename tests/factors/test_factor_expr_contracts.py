from __future__ import annotations

import pandas as pd

from tools.data.types import DataColumn
from tools.data.types import DataFreq
from tools.factors.FactorExpr import (
    ColumnRef,
    CompositeExpr,
    ConstExpr,
    EvaluateContext,
    FactorExpr,
    RollingOp,
    ShiftOp,
    CrossSectionalOp,
)
from tools.parameters import WindowParam


def _expr(seed: int = 1):
    base = ColumnRef(DataColumn.CLOSE)
    shifted = ShiftOp("shift", ConstExpr(1), base)
    rolled = RollingOp("rolling_mean", ConstExpr(5), shifted)
    return rolled if seed == 1 else CompositeExpr("mul", rolled, ConstExpr(seed))


def test_structural_key_is_stable_for_equivalent_trees():
    assert _expr()._structural_key() == _expr()._structural_key()


def test_structural_key_changes_when_formula_changes():
    assert _expr()._structural_key() != _expr(seed=2)._structural_key()


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
