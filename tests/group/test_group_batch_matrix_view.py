from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from tools.factors.tests.single_factor_test.group.group_tester import (
    BatchExecutionPlan,
    FactorGroupTester,
    GroupSimulationSpec,
)


def _make_spec(simulation_index: int, product_path_selection_id: str, factor_alias: str, signal_cols: list[str], trade_cols: list[str], group_count: int, *, flat_count: int) -> GroupSimulationSpec:
    signal_membership = np.zeros((1, flat_count, len(signal_cols)), dtype=bool)
    for gi in range(flat_count):
        signal_membership[0, gi, gi % len(signal_cols)] = True
    return GroupSimulationSpec(
        simulation_index=simulation_index,
        product_path_selection_id=product_path_selection_id,
        tester=SimpleNamespace(alias=product_path_selection_id),
        factor_alias=factor_alias,
        n_groups=group_count,
        spec={},
        shared_inputs=SimpleNamespace(
            index_list=[pd.Timestamp('2026-01-01 09:30:00')],
            signal_valid_cols=list(signal_cols),
            signal_update_mask=np.array([True]),
            T=1,
        ),
        base_membership_np=signal_membership.copy(),
        flat_group_info=[{'group_index': i, 'id': f'{product_path_selection_id}-{i}'} for i in range(flat_count)],
        group_name_map={i: f'{product_path_selection_id}-{i + 1}' for i in range(flat_count)},
        signal_products=frozenset({f'Product:{name}' for name in signal_cols}),
        signal_membership_np=signal_membership,
    )


def test_batch_execution_plan_reconstructs_merged_matrix_view(monkeypatch):
    spec_a = _make_spec(0, 'sub-a', 'FactorA', ['A', 'B'], ['A', 'B'], 2, flat_count=2)
    spec_b = _make_spec(1, 'sub-b', 'FactorB', ['B', 'C'], ['B', 'C'], 2, flat_count=1)
    spec_b.signal_membership_np[0, 0, :] = True

    def fake_remap_matrix(signal_products, signal_index):
        cols = list(signal_products)
        trade_products = list(cols)
        signal_to_trade = np.tile(np.arange(len(cols), dtype=int), (len(signal_index), 1))
        return signal_to_trade, trade_products, {}

    monkeypatch.setattr(
        'tools.factors.tests.single_factor_test.group.group_tester._build_product_remap_matrix',
        fake_remap_matrix,
    )

    tester = FactorGroupTester(
        [spec_a, spec_b],
        overlap_ratio=0.3,
        containment_ratio=0.8,
        merge_cost_ratio=10.0,
    )

    batches = tester.build_overlap_batches()
    assert len(batches) == 1

    plan = tester.build_batch_execution_plan(batches[0], batch_index=0, batch_total=1)
    assert isinstance(plan, BatchExecutionPlan)
    assert plan.batch_group_count == 3
    assert plan.trade_product_names == ['A', 'B', 'C']
    assert plan.group_slices == {0: [0, 1], 1: [2]}

    view = plan.build_matrix_view()
    assert view['batch_group_count'] == 3
    assert view['trade_product_count'] == 3
    assert view['trade_product_names'] == ['A', 'B', 'C']
    assert len(view['group_owner']) == 3

    merged = plan.merged_membership_np
    assert merged.shape == (1, 3, 3)
    np.testing.assert_array_equal(merged[0, 0], [True, False, False])
    np.testing.assert_array_equal(merged[0, 1], [False, True, False])
    np.testing.assert_array_equal(merged[0, 2], [False, True, True])

    # Local trade slices must be recoverable from the merged matrix.
    plan.validate_matrix_view()


def test_native_single_runtime_never_splits_disjoint_specs() -> None:
    specs = [
        _make_spec(0, 'sub-a', 'FactorA', ['A'], ['A'], 1, flat_count=1),
        _make_spec(1, 'sub-b', 'FactorB', ['Z'], ['Z'], 1, flat_count=1),
    ]

    ordinary = FactorGroupTester(specs, overlap_ratio=0.9)
    native = FactorGroupTester(specs, overlap_ratio=0.9, single_runtime=True)

    assert len(ordinary.build_overlap_batches()) == 2
    assert native.build_overlap_batches() == [specs]
