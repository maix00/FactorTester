from __future__ import annotations

import math

from tools.testers.backtest.policies.cross_section import (
    bottom,
    rank_cross_section,
    screen_cross_section,
    select_rank_group,
    top,
)


def test_rank_cross_section_is_descending_with_deterministic_ties():
    values = {"B": 2.0, "A": 2.0, "C": 1.0}

    assert rank_cross_section(values) == (("A", 2.0), ("B", 2.0), ("C", 1.0))


def test_screen_happens_before_rank_group_boundaries():
    values = {"A": 4.0, "B": math.nan, "C": 2.0, "D": 1.0}
    screened = screen_cross_section(values, lambda _item, value: not math.isnan(value))
    ranked = rank_cross_section(screened)

    assert select_rank_group(ranked, split_count=2, group_index=0) == frozenset({"A", "C"})
    assert select_rank_group(ranked, split_count=2, group_index=1) == frozenset({"D"})


def test_top_and_bottom_are_rank_selection_shortcuts():
    ranked = rank_cross_section({"A": 3.0, "B": 2.0, "C": 1.0})

    assert top(ranked, 2) == frozenset({"A", "B"})
    assert bottom(ranked, 2) == frozenset({"B", "C"})


def test_empty_or_out_of_range_group_is_empty():
    ranked = rank_cross_section({"A": 1.0})

    assert select_rank_group(ranked, split_count=0, group_index=0) == frozenset()
    assert select_rank_group(ranked, split_count=2, group_index=2) == frozenset()
