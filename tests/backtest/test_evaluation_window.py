from __future__ import annotations

import pandas as pd
import pytest

from tools.backtest.event_driven.contracts import (
    EvaluationSegment,
    EvaluationWindow,
)


def test_evaluation_window_marks_out_of_sample_without_resetting_time_axis() -> None:
    window = EvaluationWindow(
        pd.Timestamp("2026-01-01"),
        pd.Timestamp("2026-01-31"),
        pd.Timestamp("2026-01-20"),
    )

    assert window.segment(pd.Timestamp("2026-01-20")) == EvaluationSegment.IN_SAMPLE
    assert window.segment(pd.Timestamp("2026-01-21")) == EvaluationSegment.OUT_OF_SAMPLE
    with pytest.raises(ValueError, match="outside"):
        window.segment(pd.Timestamp("2026-02-01"))
