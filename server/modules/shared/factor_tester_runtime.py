"""Run-time FactorTester construction for test modules."""

from __future__ import annotations

from typing import Any

import server.services.page_runtime as runtime_state
from server.modules.shared.submission_model import ProductPathSelection
from server.services.session_runtime import current_user_obj


def selection_from_request(data: dict[str, Any], *, page_uuid: str) -> ProductPathSelection:
    """Resolve the product universe carried by a test request."""
    raw = data.get("product_path_selection")
    if isinstance(raw, dict):
        return ProductPathSelection.from_paths(
            str(
                raw.get("product_path_selection_id")
                or raw.get("selection_id")
                or data.get("product_path_selection_id")
                or data.get("selection_id")
                or ""
            ),
            list(raw.get("selected_paths") or raw.get("paths") or []),
            label=str(raw.get("label") or raw.get("name") or ""),
            product_group=str(raw.get("product_group") or ""),
            product_group_template_id=str(raw.get("product_group_template_id") or raw.get("path_id") or raw.get("template_id") or ""),
            source_type=str(raw.get("source_type") or "manual_selection"),
            source_key=str(raw.get("source_key") or ""),
            page_uuid=page_uuid,
        )

    selected_paths = data.get("selected_paths") or data.get("paths")
    if isinstance(selected_paths, list) and selected_paths:
        group_name = str(data.get("product_group") or data.get("group_name") or "")
        return ProductPathSelection.from_paths(
            str(
                data.get("product_path_selection_id")
                or data.get("selection_id")
                or ""
            ),
            selected_paths,
            label=str(data.get("label") or group_name),
            product_group=group_name,
            product_group_template_id=str(data.get("product_group_template_id") or data.get("path_id") or data.get("template_id") or ""),
            source_type=str(data.get("source_type") or "manual_selection"),
            source_key=str(
                data.get("source_key")
                or group_name
                or data.get("product_path_selection_id")
                or data.get("selection_id")
                or ""
            ),
            page_uuid=page_uuid,
        )

    raise AssertionError("测试配置缺少产品组设置")


def selection_for_product_path_selection(
    data: dict[str, Any],
    product_path_selection_id: str,
    *,
    page_uuid: str,
) -> ProductPathSelection:
    """Resolve one product path selection from a test request."""
    sid = str(product_path_selection_id)
    selections = data.get("product_selections")
    if isinstance(selections, dict):
        raw = selections.get(sid)
        if isinstance(raw, dict):
            return selection_from_request(
                {**raw, "product_path_selection_id": raw.get("product_path_selection_id") or raw.get("selection_id") or sid},
                page_uuid=page_uuid,
            )
    if isinstance(selections, list):
        for raw in selections:
            if isinstance(raw, dict) and str(raw.get("product_path_selection_id") or raw.get("selection_id") or raw.get("id") or "") == sid:
                return selection_from_request(
                    {**raw, "product_path_selection_id": raw.get("product_path_selection_id") or raw.get("selection_id") or sid},
                    page_uuid=page_uuid,
                )
    groups = data.get("groups")
    if isinstance(groups, list):
        groups_by_id = {
            str(group.get("id")): group
            for group in groups
            if isinstance(group, dict) and group.get("id")
        }

        def resolve_group_selection(group: dict[str, Any]) -> dict[str, Any] | None:
            raw = group.get("product_path_selection")
            if isinstance(raw, dict):
                return raw
            parent = groups_by_id.get(str(group.get("parentId") or ""))
            if isinstance(parent, dict):
                return resolve_group_selection(parent)
            return None

        for group in groups:
            if not isinstance(group, dict):
                continue
            raw = resolve_group_selection(group)
            raw_id = ""
            if isinstance(raw, dict):
                raw_id = str(
                    raw.get("product_path_selection_id")
                    or raw.get("selection_id")
                    or raw.get("id")
                    or ""
                )
            if str(group.get("product_path_selection_id") or raw_id or "") != sid:
                continue
            if isinstance(raw, dict):
                return selection_from_request(
                    {**raw, "product_path_selection_id": raw.get("product_path_selection_id") or raw.get("id") or sid},
                    page_uuid=page_uuid,
                )
    return selection_from_request({**data, "product_path_selection_id": sid}, page_uuid=page_uuid)


def create_factor_tester_for_run(
    selection: ProductPathSelection,
    *,
    page_uuid: str,
    start_dt: Any | None = None,
    end_dt: Any | None = None,
    user: Any | None = None,
):
    """Create and register the FactorTester used by a concrete test run."""
    time_entry = runtime_state.get_current_time(page_uuid)
    if time_entry is not None:
        default_start, default_end, _ = time_entry
    else:
        default_start, default_end = runtime_state.get_default_time()
    start_dt = start_dt if start_dt is not None else default_start
    end_dt = end_dt if end_dt is not None else default_end

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
    runtime_state.register_factor_tester(tester, page_uuid=page_uuid)
    return tester


def create_factor_tester_from_request(data: dict[str, Any], *, page_uuid: str, user: Any | None = None):
    selection = selection_from_request(data, page_uuid=page_uuid)
    return create_factor_tester_for_run(selection, page_uuid=page_uuid, user=user)


def create_factor_tester_for_product_path_selection(
    data: dict[str, Any],
    product_path_selection_id: str,
    *,
    page_uuid: str,
    user: Any | None = None,
):
    selection = selection_for_product_path_selection(data, product_path_selection_id, page_uuid=page_uuid)
    return create_factor_tester_for_run(selection, page_uuid=page_uuid, user=user)
