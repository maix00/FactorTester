"""Reconstruct frozen product selections from RunSpec payloads."""

from __future__ import annotations

from typing import Any

from server.modules.products.product_group_store import (
    load_product_groups,
    product_group_to_path_selection,
)
from server.services.session_runtime import current_user
from tools.products.product_path_selection import ProductPathSelection


def selection_from_request(data: dict[str, Any], *, page_uuid: str) -> ProductPathSelection:
    """Resolve the product universe carried by a test request."""
    raw = data.get("product_path_selection")
    if isinstance(raw, dict):
        selection_id = str(
            raw.get("product_path_selection_id")
            or raw.get("selection_id")
            or data.get("product_path_selection_id")
            or data.get("selection_id")
            or raw.get("id")
            or ""
        )
        raw_paths = list(raw.get("selected_paths") or raw.get("paths") or [])
        if selection_id and not raw_paths:
            username = str(
                data.get("_group_owner_username")
                or data.get("owner_username")
                or current_user()
                or ""
            )
            for group in load_product_groups(username):
                if str(group.get("id") or "") == selection_id:
                    return product_group_to_path_selection(
                        group,
                        selection_id=selection_id,
                        page_uuid=page_uuid,
                    )
        return ProductPathSelection.from_paths(
            selection_id,
            raw_paths,
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

    selection_id = str(data.get("product_path_selection_id") or data.get("selection_id") or "")
    if selection_id:
        # RunSpecs freeze product projections once under shared
        # ``product_selections``.  Resolve that immutable copy before the
        # mutable owner catalog so IC/evaluation execution does not need to
        # duplicate paths in its analysis payload.
        selections = data.get("product_selections")
        if isinstance(selections, dict) and isinstance(selections.get(selection_id), dict):
            return selection_from_request(
                {
                    **data,
                    **selections[selection_id],
                    "product_path_selection_id": selection_id,
                },
                page_uuid=page_uuid,
            )
        username = str(
            data.get("_group_owner_username")
            or data.get("owner_username")
            or current_user()
            or ""
        )
        for group in load_product_groups(username):
            if str(group.get("id") or "") == selection_id:
                return product_group_to_path_selection(
                    group,
                    selection_id=selection_id,
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
                {
                    **data,
                    **raw,
                    "product_path_selection_id": raw.get("product_path_selection_id") or raw.get("selection_id") or sid,
                },
                page_uuid=page_uuid,
            )
    if isinstance(selections, list):
        for raw in selections:
            if isinstance(raw, dict) and str(raw.get("product_path_selection_id") or raw.get("selection_id") or raw.get("id") or "") == sid:
                return selection_from_request(
                    {
                        **data,
                        **raw,
                        "product_path_selection_id": raw.get("product_path_selection_id") or raw.get("selection_id") or sid,
                    },
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
                    {
                        **data,
                        **raw,
                        "product_path_selection_id": raw.get("product_path_selection_id") or raw.get("id") or sid,
                    },
                    page_uuid=page_uuid,
                )
    return selection_from_request({**data, "product_path_selection_id": sid}, page_uuid=page_uuid)


