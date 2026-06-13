"""Cross-tester grouped backtest coordinator."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from tools.factors.FactorTester import FactorTester
from tools.factors.Parameters import FactorNextPeriodReturns
from tools.factors.tests.single_factor_test.group import _FactorGroupTestGroup
from tools.factors.tests.single_factor_test.group.core import (
    build_flat_membership_from_groups,
    _build_product_remap_matrix,
    _build_group_memberships_from_shared,
    _emit_progress,
    _load_group_trade_prices,
    _load_group_trade_returns,
    _prepare_group_shared_inputs,
    _remap_membership_to_trade,
    _resolve_group_trade_specs,
    _simulate_group_from_preloaded,
    materialize_group_outputs_from_result,
    set_batch_context,
    clear_batch_context,
    slice_group_run_result,
)
from tools.factors.tests.single_factor_test.group.metadata import GROUP_TEST_PHASES


@dataclass(slots=True)
class GroupSimulationSpec:
    simulation_index: int
    submission_id: str
    tester: FactorTester
    factor_alias: str
    n_groups: int
    spec: dict[str, Any]
    shared_inputs: Any
    base_membership_np: np.ndarray
    flat_group_info: list[dict[str, Any]]  # from build_flat_membership_from_groups
    group_name_map: dict[int, str]
    # signal-dimension fields (before remap to trade axis)
    signal_products: frozenset[str]  # frozenset of f"{cls_name}:{product_name}"
    signal_membership_np: np.ndarray  # (T, M, P_signal) — flat membership on signal axis


@dataclass(slots=True)
class BatchExecutionPlan:
    batch_index: int
    entries: list[GroupSimulationSpec]
    trade_product_names: list[str]
    trade_product_positions: dict[str, int]
    group_owner: list[dict[str, Any]]
    group_slices: dict[int, list[int]]
    merged_membership_np: np.ndarray
    merged_returns_np: np.ndarray | None = None
    merged_price_np: np.ndarray | None = None
    merged_spec_bundle: Any = None
    # Per-entry trade-dim data (built during plan construction)
    entry_trade_valid_cols: dict[int, list] | None = None
    entry_trade_membership_np: dict[int, np.ndarray] | None = None

    @property
    def batch_group_count(self) -> int:
        """Flattened group count on the merged batch axis."""
        return int(self.merged_membership_np.shape[1])

    def validate_matrix_view(self) -> None:
        """Assert that merged and per-entry matrices are losslessly aligned."""
        if self.merged_membership_np.ndim != 3:
            raise ValueError(
                f"merged_membership_np must be 3D, got shape={self.merged_membership_np.shape}"
            )
        if self.entry_trade_valid_cols is None or self.entry_trade_membership_np is None:
            raise ValueError("BatchExecutionPlan is missing entry trade axis data")
        if self.batch_group_count != len(self.group_owner):
            raise ValueError(
                f"batch_group_count mismatch: merged={self.batch_group_count}, "
                f"group_owner={len(self.group_owner)}"
            )
        if self.batch_group_count != sum(len(indices) for indices in self.group_slices.values()):
            raise ValueError(
                "group_slices do not cover the full merged batch axis"
            )
        if self.merged_membership_np.shape[2] != len(self.trade_product_names):
            raise ValueError(
                f"trade product axis mismatch: merged={self.merged_membership_np.shape[2]}, "
                f"trade_product_names={len(self.trade_product_names)}"
            )

        global_trade_positions = {
            name: idx for idx, name in enumerate(self.trade_product_names)
        }
        for entry in self.entries:
            si = entry.simulation_index
            group_indices = self.group_slices.get(si)
            local_trade_cols = self.entry_trade_valid_cols.get(si)
            local_membership = self.entry_trade_membership_np.get(si)
            if group_indices is None:
                raise ValueError(f"missing group_slices for simulation_index={si}")
            if local_trade_cols is None or local_membership is None:
                raise ValueError(f"missing trade axis data for simulation_index={si}")
            if local_membership.shape[1] != len(group_indices):
                raise ValueError(
                    f"local flat count mismatch for simulation_index={si}: "
                    f"local={local_membership.shape[1]}, slices={len(group_indices)}"
                )
            if local_membership.shape[2] != len(local_trade_cols):
                raise ValueError(
                    f"local product count mismatch for simulation_index={si}: "
                    f"local={local_membership.shape[2]}, cols={len(local_trade_cols)}"
                )
            reconstructed = np.zeros(
                (local_membership.shape[0], local_membership.shape[1], len(self.trade_product_names)),
                dtype=bool,
            )
            local_trade_positions = []
            for product in local_trade_cols:
                product_name = getattr(product, "name", str(product))
                if product_name not in global_trade_positions:
                    raise ValueError(
                        f"trade product {product_name!r} missing from merged trade axis"
                    )
                local_trade_positions.append(global_trade_positions[product_name])
            reconstructed[:, :, local_trade_positions] = local_membership
            merged_slice = self.merged_membership_np[:, group_indices, :]
            if not np.array_equal(merged_slice, reconstructed):
                raise ValueError(
                    f"merged membership mismatch for simulation_index={si}"
                )

    def build_matrix_view(self) -> dict[str, Any]:
        """Return a front-end friendly summary of the merged batch matrix."""
        return {
            "batch_index": self.batch_index,
            "batch_group_count": self.batch_group_count,
            "trade_product_count": len(self.trade_product_names),
            "trade_product_names": list(self.trade_product_names),
            "group_owner": list(self.group_owner),
            "group_slices": {int(k): list(v) for k, v in self.group_slices.items()},
        }


class FactorGroupTester:
    """Coordinate grouped backtests across one or more FactorTester instances.

    The batching rule is overlap-aware:
    - heavily overlapping trade universes are merged into one batch and should
      eventually share one simulate call;
    - weakly overlapping or disjoint universes are separated and can run in parallel.
    """

    DEFAULT_OVERLAP_RATIO = 0.35
    DEFAULT_CONTAINMENT_RATIO = 0.60
    DEFAULT_MERGE_COST_RATIO = 1.15

    def __init__(
        self,
        specs: list[GroupSimulationSpec],
        *,
        overlap_ratio: float | None = None,
        containment_ratio: float | None = None,
        merge_cost_ratio: float | None = None,
        start_dt: Optional[Any] = None,  # DataTime
        end_dt: Optional[Any] = None,    # DataTime
    ):
        self.specs = list(specs)
        self.overlap_ratio = float(
            self.DEFAULT_OVERLAP_RATIO if overlap_ratio is None else overlap_ratio
        )
        self.containment_ratio = float(
            self.DEFAULT_CONTAINMENT_RATIO if containment_ratio is None else containment_ratio
        )
        self.merge_cost_ratio = float(
            self.DEFAULT_MERGE_COST_RATIO if merge_cost_ratio is None else merge_cost_ratio
        )
        self.start_dt = start_dt
        self.end_dt = end_dt

    @classmethod
    def from_flat_groups(
        cls,
        flat_groups: list[_FactorGroupTestGroup],
        *,
        spec_index_by_group: dict[int, int] | None = None,  # group → simulation_index
        ls_configs_by_index: dict[int, list[dict] | None] | None = None,
        start_dt: Optional[Any] = None,  # DataTime
        end_dt: Optional[Any] = None,    # DataTime
        calendar_index: Optional[pd.Index],
        rebalance_mode: str,
        overlap_ratio: float | None = None,
        containment_ratio: float | None = None,
        merge_cost_ratio: float | None = None,
        progress_hook: Optional[Callable[[str], None]] = None,
    ) -> "FactorGroupTester":
        """Build a FactorGroupTester from a flat list of _FactorGroupTestGroup.

        Deduplicates (tester_id, factor_alias, n_groups) triples:
        - Runs ``_prepare_group_shared_inputs`` once per unique tester+factor_alias.
        - Runs ``_build_group_memberships_from_shared`` once per unique triple.
        - Then calls ``build_flat_membership_from_groups`` to assemble the flat
          (T, M_total, P) membership from the group list.
        """
        if spec_index_by_group is None:
            spec_index_by_group = {i: i for i in range(len(flat_groups))}

        # ── Group by tester_id ──
        tester_by_id: dict[str, tuple[FactorTester, list[_FactorGroupTestGroup]]] = {}
        for group in flat_groups:
            try:
                from server.services import runtime_state
                tester = runtime_state.get_factor_tester(group.tester_id, caller='from_flat_groups')
            except Exception:
                # tester_id may be a raw tester object in some contexts
                continue
            tester_by_id.setdefault(group.tester_id, (tester, []))[1].append(group)

        flat_groups = [
            group for group in flat_groups
            if group.tester_id in tester_by_id
        ]
        if not flat_groups:
            raise ValueError("没有找到可用于分组测试的测试器，请刷新提交列表后重试。")

        _emit_progress("info", f"分组测试准备开始，分组 {len(flat_groups)} 个")

        if progress_hook is not None:
            progress_hook(
                f"group tester prepare testers={len(tester_by_id)} groups={len(flat_groups)}"
            )

        # ── Deduplicate (tester_id, factor_alias, n_groups) triples ──
        # Map: triple → shared_inputs
        shared_inputs_by_triple: dict[tuple, Any] = {}
        signal_valid_cols_by_triple: dict[tuple, list] = {}
        memberships_by_triple: dict[tuple, np.ndarray] = {}

        # Unique factor aliases per tester
        for tester_id, (tester, tester_groups) in tester_by_id.items():
            unique_factor_aliases = list(dict.fromkeys(
                (g.factor_alias, g.tester_id) for g in tester_groups
            ))
            for factor_alias, _ in unique_factor_aliases:
                factor = tester.resolve_factor(factor_alias)
                if factor is None:
                    continue
                shared_inputs = _prepare_group_shared_inputs(
                    tester,
                    factor,
                    returns_col=FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    calendar_index=calendar_index,
                )
                # Index by a canonical triple key
                triple = (tester_id, factor_alias, 0)  # placeholder n_groups
                # Collect unique n_groups for this (tester, factor)
                unique_n_groups = sorted({
                    g.n_groups for g in tester_groups
                    if g.factor_alias == factor_alias
                })
                membership_list = _build_group_memberships_from_shared(
                    factor,
                    shared_inputs,
                    group_counts=unique_n_groups,
                    rebalance_mode=rebalance_mode,
                )
                for n_groups, membership_np in zip(unique_n_groups, membership_list):
                    triple = (tester_id, factor_alias, n_groups)
                    shared_inputs_by_triple[triple] = shared_inputs
                    signal_valid_cols_by_triple[triple] = shared_inputs.signal_valid_cols
                    memberships_by_triple[triple] = membership_np

        missing_triples = sorted({
            group.triple_key
            for group in flat_groups
            if group.triple_key not in shared_inputs_by_triple
        })
        if missing_triples:
            raise ValueError(
                "部分分组未能准备因子数据，请刷新提交列表后重试。"
                f"缺失三元组: {missing_triples}"
            )

        # ── Build GroupSimulationSpec per (simulation_index, triple) ──
        # Each spec must stay on a single factor/tester signal axis. Different
        # factors may have different valid product columns, so they are merged
        # later on the trade axis by BatchExecutionPlan.
        built_specs: list[GroupSimulationSpec] = []
        groups_by_spec_key: dict[tuple[int, tuple], list[_FactorGroupTestGroup]] = {}
        for flat_idx, group in enumerate(flat_groups):
            si = spec_index_by_group.get(flat_idx, flat_idx)
            groups_by_spec_key.setdefault((si, group.triple_key), []).append(group)

        for (si, triple), spec_groups in groups_by_spec_key.items():
            first_group = spec_groups[0]
            factor_alias = first_group.factor_alias
            n_groups = first_group.n_groups
            shared = shared_inputs_by_triple.get(triple)
            base_membership = memberships_by_triple.get(triple)
            if shared is None or base_membership is None:
                continue
            tester = tester_by_id[first_group.tester_id][0]
            factor = tester.resolve_factor(factor_alias)
            if factor is None:
                continue

            try:
                si_membership_np, si_flat_info = build_flat_membership_from_groups(
                    spec_groups,
                    shared_inputs_by_triple=shared_inputs_by_triple,
                    signal_valid_cols_by_triple=signal_valid_cols_by_triple,
                    memberships_by_triple=memberships_by_triple,
                )
            except Exception as e:
                raise RuntimeError(
                    f"build_flat_membership_from_groups failed: si={si} triple={triple} "
                    f"n_groups={n_groups} factor_alias={factor_alias} "
                    f"base_membership.shape={base_membership.shape} "
                    f"spec_groups_count={len(spec_groups)} "
                    f"group_indices={[g.group_index for g in spec_groups]} "
                    f"| {type(e).__name__}: {e}"
                ) from e
            group_name_map = {
                local_idx: str(group.name or group.key or f"group_{local_idx}")
                for local_idx, group in enumerate(spec_groups)
            }

            built_specs.append(
                GroupSimulationSpec(
                    simulation_index=si,
                    submission_id=first_group.tester_id,
                    tester=tester,
                    factor_alias=factor_alias,
                    n_groups=n_groups,
                    spec={"ls_configs": (ls_configs_by_index or {}).get(si)},
                    shared_inputs=shared,
                    base_membership_np=base_membership,
                    flat_group_info=si_flat_info,
                    group_name_map=group_name_map,
                    signal_products=frozenset(
                        f"{type(product).__name__}:{getattr(product, 'name', str(product))}"
                        for product in shared.signal_valid_cols
                    ),
                    signal_membership_np=si_membership_np,
                )
            )

        # ---------------------------------------------------------------
        # Unified trim: when calendar_index is provided, each factor's
        # shared_inputs covers the full calendar_index but may have
        # leading/trailing rows where all factors are NaN.  Trim to the
        # union of all factors' signal-present rows so downstream
        # simulation does not waste time on useless bar rows.
        # ---------------------------------------------------------------
        if built_specs and calendar_index is not None and len(calendar_index) > 0:
            T_full = len(calendar_index)
            unified_mask = np.zeros(T_full, dtype=bool)
            for spec in built_specs:
                unified_mask |= spec.shared_inputs.signal_update_mask
            unified_pos = np.flatnonzero(unified_mask)
            if len(unified_pos) > 0:
                unified_first = int(unified_pos[0])
                unified_last = int(unified_pos[-1]) + 1
            else:
                unified_first, unified_last = 0, T_full

            if unified_first > 0 or unified_last < T_full:
                for spec in built_specs:
                    si = spec.shared_inputs
                    t0, t1 = unified_first, unified_last
                    spec.signal_membership_np = spec.signal_membership_np[t0:t1]
                    spec.base_membership_np = spec.base_membership_np[t0:t1]
                    si.signal_update_mask = si.signal_update_mask[t0:t1]
                    si.table_np = si.table_np[t0:t1]
                    si.signal_returns_np = si.signal_returns_np[t0:t1]
                    si.present_np = si.present_np[t0:t1]
                    si.table_src = si.table_src.iloc[t0:t1]
                    si.returns_src = si.returns_src.iloc[t0:t1]
                    si.price_src = si.price_src.iloc[t0:t1]
                    si.index_list = si.index_list[t0:t1]
                    si.T = t1 - t0

        return cls(
            built_specs,
            overlap_ratio=overlap_ratio,
            containment_ratio=containment_ratio,
            merge_cost_ratio=merge_cost_ratio,
            start_dt=start_dt,
            end_dt=end_dt,
        )

    @staticmethod
    def compute_overlap_ratio(lhs: frozenset[str], rhs: frozenset[str]) -> float:
        if not lhs or not rhs:
            return 0.0
        inter = len(lhs.intersection(rhs))
        union = len(lhs.union(rhs))
        return 0.0 if union <= 0 else inter / union

    @staticmethod
    def compute_containment_ratio(lhs: frozenset[str], rhs: frozenset[str]) -> float:
        if not lhs or not rhs:
            return 0.0
        inter = len(lhs.intersection(rhs))
        smaller = min(len(lhs), len(rhs))
        return 0.0 if smaller <= 0 else inter / smaller

    @staticmethod
    def _flattened_group_count(entry: GroupSimulationSpec) -> int:
        return int(entry.signal_membership_np.shape[1])

    def _should_link_specs(self, left: GroupSimulationSpec, right: GroupSimulationSpec) -> bool:
        overlap = self.compute_overlap_ratio(left.signal_products, right.signal_products)
        containment = self.compute_containment_ratio(left.signal_products, right.signal_products)
        return overlap >= self.overlap_ratio or containment >= self.containment_ratio

    def _estimate_batch_cost(self, batch: list[GroupSimulationSpec]) -> tuple[float, float]:
        if not batch:
            return 0.0, 0.0
        separate_cost = float(sum(
            self._flattened_group_count(entry) * len(entry.signal_products)
            for entry in batch
        ))
        merged_products: set[str] = set()
        merged_group_count = 0
        for entry in batch:
            merged_products.update(entry.signal_products)
            merged_group_count += self._flattened_group_count(entry)
        merged_cost = float(merged_group_count * len(merged_products))
        return separate_cost, merged_cost

    def _split_component_by_cost(self, component: list[GroupSimulationSpec]) -> list[list[GroupSimulationSpec]]:
        if len(component) <= 1:
            return [component]
        separate_cost, merged_cost = self._estimate_batch_cost(component)
        if separate_cost <= 0:
            return [component]
        if merged_cost <= separate_cost * self.merge_cost_ratio:
            return [component]
        return [[entry] for entry in component]

    def build_overlap_batches(self) -> list[list[GroupSimulationSpec]]:
        """Cluster specs by product-coverage overlap; then merge batches that share an LS config.

        LS-config-aware merging:
          Each ``GroupSimulationSpec.spec`` may carry ``ls_configs`` (per-entry LS)
          and/or ``ls_spec_indices`` (spec indices that share an LS config).
          If an LS config's legs span multiple overlap-based batches, those batches
          are merged so the LS computation can see all groups in one simulate call.

        Future-proof: when an LS config leg references (simulation_index, group_index)
        pairs directly, the same merging rule applies — any batch that contains at
        least one of the referenced spec indices will be merged.
        """
        if not self.specs:
            return []

        # ── 1. Cluster by product-coverage overlap ──
        adjacency: dict[int, set[int]] = {idx: set() for idx in range(len(self.specs))}
        for (i, left), (j, right) in combinations(enumerate(self.specs), 2):
            if self._should_link_specs(left, right):
                adjacency[i].add(j)
                adjacency[j].add(i)

        visited: set[int] = set()
        batches: list[list[GroupSimulationSpec]] = []
        for start in range(len(self.specs)):
            if start in visited:
                continue
            stack = [start]
            component: list[GroupSimulationSpec] = []
            visited.add(start)
            while stack:
                idx = stack.pop()
                component.append(self.specs[idx])
                for nxt in adjacency[idx]:
                    if nxt in visited:
                        continue
                    visited.add(nxt)
                    stack.append(nxt)
            batches.extend(self._split_component_by_cost(component))

        # ── 2. Collect LS config shared-spec constraints ──
        # Build spec_index → batch_index mapping
        spec_to_batch: dict[int, int] = {}
        for bi, batch in enumerate(batches):
            for entry in batch:
                spec_to_batch[entry.simulation_index] = bi

        # Gather all sets of spec indices that must stay together.
        # (a) per-entry ls_configs: long/short groups are local to the entry —
        #     they refer to groups within the same simulation_index, so no
        #     product-coverage constraint is needed today.  We collect the entry's
        #     own spec index as a single-element set anyway for future-proofing.
        # (b) ls_spec_indices: explicit spec-level LS sharing constraints.
        ls_spec_groups: list[set[int]] = []
        for entry in self.specs:
            ls_configs = (entry.spec or {}).get('ls_configs')
            if isinstance(ls_configs, list) and ls_configs:
                # Future: ls_configs legs may reference (sim_index, group) pairs.
                # For now, all legs are within the same entry.
                ls_spec_groups.append({entry.simulation_index})
            cross_indices = (entry.spec or {}).get('ls_spec_indices')
            if isinstance(cross_indices, (list, set)) and cross_indices:
                group_set = set(cross_indices)
                group_set.add(entry.simulation_index)
                ls_spec_groups.append(group_set)

        # ── 3. Merge batches connected by LS constraints ──
        if ls_spec_groups:
            # Union-Find over batch indices
            batch_parent = {i: i for i in range(len(batches))}

            def _find(x):
                while batch_parent[x] != x:
                    batch_parent[x] = batch_parent[batch_parent[x]]
                    x = batch_parent[x]
                return x

            def _union(a, b):
                ra, rb = _find(a), _find(b)
                if ra != rb:
                    batch_parent[ra] = rb

            for group in ls_spec_groups:
                batch_indices = set()
                for si in group:
                    bi = spec_to_batch.get(si)
                    if bi is not None:
                        batch_indices.add(bi)
                if len(batch_indices) > 1:
                    it = iter(batch_indices)
                    first = next(it)
                    for other in it:
                        _union(first, other)

            # Re-group
            merged: dict[int, list[GroupSimulationSpec]] = {}
            for bi, batch in enumerate(batches):
                root = _find(bi)
                merged.setdefault(root, []).extend(batch)
            batches = list(merged.values())

        return batches

    def build_batch_labels(self) -> list[list[str]]:
        return [
            [f"{entry.submission_id}|{entry.factor_alias}|{entry.n_groups}" for entry in batch]
            for batch in self.build_overlap_batches()
        ]

    def build_batch_execution_plan(
        self,
        batch: list[GroupSimulationSpec],
        *,
        batch_index: int,
        batch_total: int | None = None,
    ) -> BatchExecutionPlan:
        if not batch:
            raise ValueError("batch must not be empty")
        index_list = batch[0].shared_inputs.index_list
        T = len(index_list)
        batch_total_value = int(batch_total or 0)
        batch_label = f"{batch_index + 1}/{batch_total_value}" if batch_total_value > 0 else str(batch_index + 1)

        # ── Step 1: deduplicate (signal_valid_cols, signal_index) combos,
        #           build product remap matrix once per unique key ──
        # We use id(tuple) as a stable key for the same signal_valid_cols list
        # and the same index_list across specs sharing a tester+factor_alias.
        _remap_cache: dict[int, tuple[np.ndarray, list]] = {}
        def _remap_key(entry: GroupSimulationSpec) -> int:
            # signal_valid_cols identity + index_list identity is enough
            # because same FactorTester + same factor_alias → same SharedInputs
            return id(entry.shared_inputs)

        entry_trade_valid_cols: dict[int, list] = {}
        entry_trade_membership_np: dict[int, np.ndarray] = {}
        seen_simulation_indices: set[int] = set()

        remap_total = len(batch)
        _emit_progress(
            "remap",
            f"批次 {batch_label} 开始产品重映射，提交 {remap_total} 个",
            batch_index=batch_index,
            batch_total=batch_total_value,
            completed=0,
            total=remap_total,
        )
        for remap_idx, entry in enumerate(batch, start=1):
            if entry.simulation_index in seen_simulation_indices:
                raise ValueError(
                    f"批次 {batch_label} 中 simulation_index={entry.simulation_index} 出现多个分组规格，"
                    "这会导致分组切片被覆盖。请按 tester/factor/n_groups 拆分 simulation_index。"
                )
            seen_simulation_indices.add(entry.simulation_index)
            key = _remap_key(entry)
            if key not in _remap_cache:
                signal_to_trade, trade_products, _ = _build_product_remap_matrix(
                    entry.shared_inputs.signal_valid_cols,
                    entry.shared_inputs.index_list,
                )
                _remap_cache[key] = (signal_to_trade, list(trade_products))
            signal_to_trade, trade_cols = _remap_cache[key]
            try:
                trade_membership_np = _remap_membership_to_trade(
                    entry.signal_membership_np,
                    signal_to_trade,
                    len(trade_cols),
                )
            except IndexError as e:
                raise IndexError(
                    f"remap index error: si={si} signal_membership_np.shape={entry.signal_membership_np.shape} "
                    f"signal_to_trade.shape={signal_to_trade.shape} trade_cols={len(trade_cols)} | {e}"
                ) from e
            si = entry.simulation_index
            entry_trade_valid_cols[si] = trade_cols
            entry_trade_membership_np[si] = trade_membership_np
            _emit_progress(
                "remap",
                f"批次 {batch_label} 产品重映射 {remap_idx}/{remap_total}",
                batch_index=batch_index,
                batch_total=batch_total_value,
                completed=remap_idx,
                total=remap_total,
            )

        # ── Step 2: merge all trade products into unified axis ──
        trade_product_names = sorted({
            getattr(product, "name", str(product))
            for entry in batch
            for product in entry_trade_valid_cols[entry.simulation_index]
        })
        trade_product_positions = {
            product_name: idx
            for idx, product_name in enumerate(trade_product_names)
        }

        batch_flat_count = int(sum(
            entry_trade_membership_np[entry.simulation_index].shape[1]
            for entry in batch
        ))
        expected_flat_count = int(sum(len(entry.flat_group_info) for entry in batch))
        if batch_flat_count != expected_flat_count:
            raise ValueError(
                f"批次 {batch_index + 1} 扁平组数量不一致："
                f"entry flat groups={expected_flat_count}, "
                f"trade membership batch_flat_count={batch_flat_count}"
            )
        merged_membership_np = np.zeros(
            (T, batch_flat_count, len(trade_product_names)), dtype=bool,
        )
        group_owner: list[dict[str, Any]] = []
        group_slices: dict[int, list[int]] = {}

        group_offset = 0
        for entry in batch:
            si = entry.simulation_index
            local = entry_trade_membership_np[si]
            local_flat_count = int(local.shape[1])
            if local_flat_count != len(entry.flat_group_info):
                raise ValueError(
                    f"批次 {batch_index + 1} 提交 {si} 扁平组数量不一致："
                    f"flat groups={len(entry.flat_group_info)}, "
                    f"trade membership flat_count={local_flat_count}"
                )
            
            product_indices = np.asarray(
                [trade_product_positions[getattr(product, "name", str(product))]
                 for product in entry_trade_valid_cols[si]],
                dtype=int,
            )
            try:
                merged_membership_np[
                    :,
                    group_offset:group_offset + local_flat_count,
                    product_indices,
                ] = local
            except IndexError as e:
                raise IndexError(
                    f"merge index error: T={T} batch_flat_count={batch_flat_count} P={len(trade_product_names)} "
                    f"group_offset={group_offset} local_flat_count={local_flat_count} "
                    f"local_shape={local.shape} product_indices={product_indices.tolist()} "
                    f"merged_shape={merged_membership_np.shape} si={si} | {e}"
                ) from e
            group_slices[si] = list(range(group_offset, group_offset + local_flat_count))
            for local_group_idx in range(local_flat_count):
                group_label = entry.group_name_map.get(local_group_idx, f"group_{local_group_idx}")
                group_owner.append({
                    "simulation_index": si,
                    "submission_id": entry.submission_id,
                    "factor_alias": entry.factor_alias,
                    "requested_n_groups": entry.n_groups,
                    "group_index": local_group_idx,
                    "group_name": group_label,
                })
            group_offset += local_flat_count

        plan = BatchExecutionPlan(
            batch_index=batch_index,
            entries=list(batch),
            trade_product_names=trade_product_names,
            trade_product_positions=trade_product_positions,
            group_owner=group_owner,
            group_slices=group_slices,
            merged_membership_np=merged_membership_np,
            entry_trade_valid_cols=entry_trade_valid_cols,
            entry_trade_membership_np=entry_trade_membership_np,
        )
        plan.validate_matrix_view()
        return plan

    def build_batch_execution_plans(self) -> list[BatchExecutionPlan]:
        batches = self.build_overlap_batches()
        batch_total = len(batches)
        return [
            self.build_batch_execution_plan(batch, batch_index=batch_index, batch_total=batch_total)
            for batch_index, batch in enumerate(batches)
        ]

    def enrich_batch_execution_plan(
        self,
        plan: BatchExecutionPlan,
        *,
        fee: float,
        fee_modifications: list | None = None,
        use_closetoday: bool = False,
    ) -> BatchExecutionPlan:
        first_entry = plan.entries[0]
        T = len(first_entry.shared_inputs.index_list)
        P = len(plan.trade_product_names)
        merged_returns_np = np.full((T, P), np.nan, dtype=float)
        merged_price_np = np.full((T, P), np.nan, dtype=float)
        global_products_by_name: dict[str, Any] = {}

        if plan.entry_trade_valid_cols is None:
            raise ValueError("BatchExecutionPlan has no entry_trade_valid_cols (build_batch_execution_plan must be called first)")

        total_entries = len(plan.entries)
        for entry_idx, entry in enumerate(plan.entries, start=1):
            _emit_progress("trade_data", f"加载交易数据 {entry_idx}/{total_entries}",
                           completed=entry_idx - 1, total=total_entries)
            factor = entry.tester.resolve_factor(entry.factor_alias)
            if factor is None:
                raise ValueError(f"未找到因子 {entry.factor_alias}")
            trade_valid_cols = plan.entry_trade_valid_cols.get(entry.simulation_index)
            if not trade_valid_cols:
                continue
            local_returns_np = _load_group_trade_returns(
                entry.tester,
                factor,
                trade_valid_cols=list(trade_valid_cols),
                returns_col=FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED,
                source_freq=entry.shared_inputs.source_freq,
                effective_return_freq=entry.shared_inputs.effective_return_freq,
                start_dt=self.start_dt,
                end_dt=self.end_dt,
                index_list=entry.shared_inputs.index_list,
            )
            local_price_np = _load_group_trade_prices(
                factor,
                trade_valid_cols=list(trade_valid_cols),
                price_col=entry.shared_inputs.price_col,
                source_freq=entry.shared_inputs.source_freq,
                start_dt=self.start_dt,
                end_dt=self.end_dt,
                index_list=entry.shared_inputs.index_list,
            )
            for local_col_idx, product in enumerate(trade_valid_cols):
                product_name = getattr(product, "name", str(product))
                global_products_by_name.setdefault(product_name, product)
                global_col_idx = plan.trade_product_positions[product_name]
                local_returns_col = np.asarray(local_returns_np[:, local_col_idx], dtype=float)
                local_price_col = np.asarray(local_price_np[:, local_col_idx], dtype=float)
                returns_missing = np.isnan(merged_returns_np[:, global_col_idx])
                price_missing = np.isnan(merged_price_np[:, global_col_idx])
                merged_returns_np[returns_missing, global_col_idx] = local_returns_col[returns_missing]
                merged_price_np[price_missing, global_col_idx] = local_price_col[price_missing]

        ordered_trade_products = [global_products_by_name[name] for name in plan.trade_product_names]
        signal_valid_cols = list(dict.fromkeys(
            product
            for entry in plan.entries
            for product in entry.shared_inputs.signal_valid_cols
        ))
        plan.merged_returns_np = merged_returns_np
        plan.merged_price_np = merged_price_np
        plan.merged_spec_bundle = _resolve_group_trade_specs(
            signal_valid_cols=signal_valid_cols,
            valid_cols=ordered_trade_products,
            fee=fee,
            fee_modifications=fee_modifications,
            use_closetoday=use_closetoday,
        )
        return plan

    def _run_merged_batch(
        self,
        plan: BatchExecutionPlan,
        *,
        batch_index: int,
        batch_total: int,
        fee: float,
        fee_modifications: list | None = None,
        use_closetoday: bool,
        initial_capital: float,
        rebalance_mode: str,
    ) -> list[dict[str, Any]]:
        batch_label = f"{batch_index + 1}/{batch_total}"
        set_batch_context(batch_index, batch_total, batch_label)
        try:
            _emit_progress("trade_data", f"批次 {batch_label} 加载交易数据",
                           completed=0, total=1)
            plan = self.enrich_batch_execution_plan(plan, fee=fee, fee_modifications=fee_modifications, use_closetoday=use_closetoday)
            first_entry = plan.entries[0]
            first_factor = first_entry.tester.resolve_factor(first_entry.factor_alias)
            if first_factor is None or plan.merged_returns_np is None or plan.merged_price_np is None or plan.merged_spec_bundle is None:
                raise ValueError("merged batch plan is incomplete")
            spec_bundle = plan.merged_spec_bundle
            returns_raw = np.asarray(plan.merged_returns_np, dtype=float)
            returns_filled = np.where(np.isnan(returns_raw) | np.isinf(returns_raw) | (returns_raw <= -1.0), 0.0, returns_raw)
            group_name_map = {
                idx: str(owner.get("group_name") or f"group_{idx}")
                for idx, owner in enumerate(plan.group_owner)
            }
            entries_by_simulation_index = {entry.simulation_index: entry for entry in plan.entries}

            # Build per-group configs: one config dict per global group index.
            # Each entry contributes its groups via flat_group_info.
            batch_flat_count = plan.merged_membership_np.shape[1]
            group_configs: list[dict] = [{} for _ in range(batch_flat_count)]
            for simulation_index, group_indices in plan.group_slices.items():
                entry = entries_by_simulation_index[simulation_index]
                local_to_global = {
                    local_idx: global_idx
                    for local_idx, global_idx in enumerate(group_indices)
                }
                # Use flat_group_info to populate configs
                for flat_pos, info in enumerate(entry.flat_group_info):
                    group_configs[local_to_global.get(flat_pos, flat_pos)] = dict(info)

            _emit_progress("trade_data", f"批次 {batch_label} 交易数据就绪，扁平组 {batch_flat_count} 个，品种 {len(spec_bundle.valid_cols)} 个",
                           completed=1, total=1)

            _emit_progress("simulate", f"批次 {batch_label} 开始模拟", completed=0, total=1)
            try:
                _, _, _, merged_group_result = _simulate_group_from_preloaded(
                first_factor,
                membership_np=plan.merged_membership_np,
            returns_filled=returns_filled,
            price_np=np.asarray(plan.merged_price_np, dtype=float),
            valid_cols=spec_bundle.valid_cols,
            index_list=list(first_entry.shared_inputs.index_list),
            n_names=group_name_map,
            group_configs=group_configs,
            use_closetoday_vec=spec_bundle.use_closetoday_vec,
            rebalance_mode=rebalance_mode,
            initial_capital=initial_capital,
            multi_session_active=any(bool(entry.shared_inputs.multi_session_active) for entry in plan.entries),
            start_dt=self.start_dt,
            end_dt=self.end_dt,
            source_freq=first_entry.shared_inputs.source_freq,
            open_ratio_vec=spec_bundle.open_ratio_vec,
            close_ratio_vec=spec_bundle.close_ratio_vec,
            close_today_ratio_vec=spec_bundle.close_today_ratio_vec,
            open_fixed_vec=spec_bundle.open_fixed_vec,
            close_fixed_vec=spec_bundle.close_fixed_vec,
            close_today_fixed_vec=spec_bundle.close_today_fixed_vec,
            point_value_vec=spec_bundle.point_value_vec,
            min_tick_vec=spec_bundle.min_tick_vec,
            min_trade_quantity_vec=spec_bundle.min_trade_quantity_vec,
            long_margin_ratio_vec=spec_bundle.long_margin_ratio_vec,
            is_margin_traded_vec=spec_bundle.is_margin_traded_vec,
            positions_by_variety_code_lower=spec_bundle.positions_by_variety_code_lower,
        )
            except IndexError as e:
                raise IndexError(
                    f"simulate index error: batch_flat_count={batch_flat_count} "
                    f"merged_membership_np.shape={plan.merged_membership_np.shape} "
                    f"returns_filled.shape={returns_filled.shape} "
                    f"plan.merged_price_np.shape={plan.merged_price_np.shape if plan.merged_price_np is not None else None} "
                    f"P={len(spec_bundle.valid_cols)} | {e}"
                ) from e

            out: list[dict[str, Any]] = []
            for simulation_index, group_indices in plan.group_slices.items():
                entry = entries_by_simulation_index[simulation_index]
                factor = entry.tester.resolve_factor(entry.factor_alias)
                if factor is None:
                    raise ValueError(f"未找到因子 {entry.factor_alias}")
                try:
                    sliced_result = slice_group_run_result(merged_group_result, group_indices)
                except IndexError as e:
                    raise IndexError(
                        f"slice index error: simulation_index={simulation_index} group_indices={group_indices} "
                        f"merged_group_result.returns_np.shape={merged_group_result.returns_np.shape} "
                        f"plan.group_slices={plan.group_slices} | {e}"
                    ) from e
                entry.tester._get_result(factor).group_result = sliced_result
                returns_dict, report_df, cum_np, idx_list = materialize_group_outputs_from_result(sliced_result)
                out.append({
                    "simulation_index": entry.simulation_index,
                    "submission_id": entry.submission_id,
                    "factor_alias": entry.factor_alias,
                    "n_groups": entry.n_groups,
                    "factor": factor,
                    "returns_dict": returns_dict,
                    "report_df": report_df,
                    "cum_np": cum_np,
                    "idx_list": idx_list,
                    "group_result": sliced_result,
                    "flat_group_info": entry.flat_group_info,
                    "ls_configs": entry.spec.get("ls_configs"),
                    "tester": entry.tester,
                })
            return out
        finally:
            clear_batch_context()

    def run(
        self,
        *,
        fee: float,
        fee_modifications: list | None = None,
        use_closetoday: bool,
        initial_capital: float,
        rebalance_mode: str,
        start_dt: Optional[Any] = None,  # DataTime
        end_dt: Optional[Any] = None,    # DataTime
        calendar_index: Optional[pd.Index],
        progress_hook: Optional[Callable[[str], None]] = None,
        max_workers: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        total_entries = len(self.specs)

        batches = self.build_overlap_batches()
        total_groups = sum(
            self._flattened_group_count(entry)
            for batch in batches
            for entry in batch
        )
        total_batches = len(batches)

        _emit_progress("init", f"分组测试开始，批次 {total_batches} 个，提交 {total_entries} 个，重叠阈值 {self.overlap_ratio:.2f}",
                       total_batches=total_batches, total_entries=total_entries, total_groups=total_groups,
                       phases=GROUP_TEST_PHASES)
        plans = [
            self.build_batch_execution_plan(batch, batch_index=batch_index, batch_total=total_batches)
            for batch_index, batch in enumerate(batches)
        ]
        if progress_hook is not None:
            progress_hook(
                f"group tester run start specs={len(self.specs)} batches={len(batches)} overlap_ratio={self.overlap_ratio:.2f}"
            )
            for plan in plans:
                progress_hook(
                    f"group tester plan batch={plan.batch_index + 1}/{len(plans)} "
                    f"entries={len(plan.entries)} groups={len(plan.group_owner)} "
                    f"trade_products={len(plan.trade_product_names)}"
                )

        batches_completed = 0

        def _run_batch(batch_idx: int, batch: list[GroupSimulationSpec]) -> list[dict[str, Any]]:
            nonlocal batches_completed
            plan = plans[batch_idx]
            batch_label = f"{batch_idx + 1}/{total_batches}"
            _emit_progress("batch", f"批次 {batch_label} 开始，提交 {len(batch)} 个，分组 {len(plan.group_owner)} 个，交易品种 {len(plan.trade_product_names)} 个",
                           batch_index=batch_idx, batch_total=total_batches, batch_entries=len(batch),
                           completed=batches_completed, total=total_batches)
            if progress_hook is not None:
                progress_hook(
                    f"group tester batch start {batch_idx + 1}/{total_batches} size={len(batch)}"
                )
                progress_hook(
                    f"group tester batch merged simulate {batch_idx + 1}/{total_batches} "
                    f"entries={len(batch)} groups={len(plan.group_owner)} products={len(plan.trade_product_names)}"
                )
            out = self._run_merged_batch(
                plan,
                batch_index=batch_idx,
                batch_total=total_batches,
                fee=fee,
                fee_modifications=fee_modifications,
                use_closetoday=use_closetoday,
                initial_capital=initial_capital,
                rebalance_mode=rebalance_mode,
            )
            batches_completed += 1
            _emit_progress("batch", f"批次 {batch_label} 完成，提交 {len(batch)} 个",
                           batch_index=batch_idx, batch_total=total_batches, batch_entries=len(batch),
                           completed=batches_completed, total=total_batches)
            if progress_hook is not None:
                progress_hook(f"group tester batch done {batch_idx + 1}/{total_batches} size={len(batch)} merged=true")
            return out

        results: list[dict[str, Any]] = []
        worker_count = max_workers or min(max(len(batches), 1), 6)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(_run_batch, batch_idx, batch): batch_idx
                for batch_idx, batch in enumerate(batches)
            }
            for future in as_completed(futures):
                results.extend(future.result())

        results.sort(key=lambda item: int(item.get("simulation_index", 0)))
        _emit_progress("batch", f"全部批次完成，批次 {total_batches} 个，完成提交 {len(results)} 个",
                       completed=total_batches, total=total_batches)
        return results
