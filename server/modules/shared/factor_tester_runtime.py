"""Run-time FactorTester construction for test modules."""

from __future__ import annotations

from typing import Any

import pandas as pd

import server.services.page_runtime as runtime_state
from tools.products.product_path_selection import ProductPathSelection
from server.services.session_runtime import current_user, current_user_obj
from tools.data.types import DataTime


def _as_data_time(value: Any) -> DataTime | None:
    if value is None:
        return None
    if isinstance(value, DataTime):
        return value
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("Asia/Shanghai")
    return DataTime(ts=ts)


def require_run_window(
    start_dt: Any | None,
    end_dt: Any | None,
) -> tuple[DataTime, DataTime]:
    """Return one explicit, ordered run window; never consult PageRuntime."""
    start = _as_data_time(start_dt)
    end = _as_data_time(end_dt)
    missing = [
        name for name, value in (("start_date", start), ("end_date", end))
        if value is None or value.ts is None
    ]
    if missing:
        raise ValueError(f"运行时间范围缺失: {', '.join(missing)}")
    if start.sort_key() > end.sort_key():
        raise ValueError("运行时间范围错误: start_date 必须早于或等于 end_date")
    return start, end


from server.modules.shared.run_spec_resolution.products import (
    selection_for_product_path_selection,
    selection_from_request,
)


def create_factor_tester_for_run(
    selection: ProductPathSelection,
    *,
    page_uuid: str,
    start_dt: Any,
    end_dt: Any,
    user: Any | None = None,
):
    """Create and register the FactorTester used by a concrete test run."""
    start_dt, end_dt = require_run_window(start_dt, end_dt)

    from tools.factors.FactorTester import FactorTester

    tester = FactorTester(
        products=selection.products,
        alias=selection.selection_id,
        start_dt=start_dt,
        end_dt=end_dt,
        user=user if user is not None else current_user_obj(),
    )
    tester.selected_paths = list(selection.selected_paths)
    tester.label = selection.label
    tester.product_group = selection.product_group
    tester.product_group_template_id = selection.product_group_template_id
    tester.selection_source_type = selection.source_type
    tester.selection_source_key = selection.source_key
    tester.product_selection = selection
    tester._page_uuid = page_uuid
    runtime_state.register_page_object(runtime_state.FACTOR_TESTER, tester, page_uuid=page_uuid)
    return tester


def create_isolated_factor_tester_for_run(
    selection: ProductPathSelection,
    *,
    run_id: str,
    start_dt: Any,
    end_dt: Any,
    user: Any | None = None,
):
    """Create a worker-local tester without reading or registering PageRuntime."""
    start_dt, end_dt = require_run_window(start_dt, end_dt)

    from tools.factors.FactorTester import FactorTester

    tester = FactorTester(
        products=selection.products,
        alias=f"run:{str(run_id)}",
        start_dt=start_dt,
        end_dt=end_dt,
        user=user,
    )
    tester.selected_paths = list(selection.selected_paths)
    tester.label = selection.label
    tester.product_group = selection.product_group
    tester.product_group_template_id = selection.product_group_template_id
    tester.selection_source_type = selection.source_type
    tester.selection_source_key = selection.source_key
    tester.product_selection = selection
    tester._page_uuid = ""
    return tester


def create_factor_tester_for_product_path_selection(
    data: dict[str, Any],
    product_path_selection_id: str,
    *,
    page_uuid: str,
    start_dt: Any,
    end_dt: Any,
    user: Any | None = None,
):
    selection = selection_for_product_path_selection(data, product_path_selection_id, page_uuid=page_uuid)
    return create_factor_tester_for_run(
        selection,
        page_uuid=page_uuid,
        start_dt=start_dt,
        end_dt=end_dt,
        user=user,
    )
