import numpy as np
import pandas as pd

from tools.data.types import DataTime
from tools.factors.tests.single_factor_test.group import _FactorGroupTestGroup
from tools.factors.tests.single_factor_test.group.core import build_flat_membership_from_groups


class SharedInputs:
    def __init__(self, index):
        self.index_list = index
        self.signal_valid_cols = ["IF.CFE"]
        self.T = len(index)


def test_group_signal_window_masks_membership_only_for_that_group():
    index = pd.Index(pd.to_datetime([
        "2025-01-02 09:00",
        "2025-01-02 10:00",
        "2025-01-02 11:00",
    ]))
    group = _FactorGroupTestGroup(
        tester_id="selection-1",
        factor_alias="FactorA",
        n_groups=2,
        group_index=0,
        key="A1",
        name="A1",
        signal_start_dt=DataTime.parse("2025-01-02 10:00", precision="exact"),
        signal_end_dt=DataTime.parse("2025-01-02 10:00", precision="exact"),
    )
    base_membership = np.ones((3, 2, 1), dtype=bool)

    membership, info = build_flat_membership_from_groups(
        [group],
        shared_inputs_by_triple={group.triple_key: SharedInputs(index)},
        signal_valid_cols_by_triple={group.triple_key: ["IF.CFE"]},
        memberships_by_triple={group.triple_key: base_membership},
    )

    assert membership[:, 0, 0].tolist() == [False, True, False]
    assert info[0]["signal_start_dt"] == group.signal_start_dt
    assert info[0]["signal_end_dt"] == group.signal_end_dt
