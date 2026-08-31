"""Instance-info for a setting value.

A setting may declare `instance_class` (parallel to info_overlay): the backend
"页内活对象" class its value maps to. This endpoint looks that object up in the
unified page_runtime registry by (kind, id) — the ALREADY-LIVE object under page
lifecycle management — and serializes it. It never rebuilds the object from the
frontend value.
"""
from __future__ import annotations

import importlib
from typing import Any, Optional

from flask import jsonify, request

import server.services.page_runtime as page_runtime
from server.services.http_auth import login_required
from server.services.session_runtime import current_user
from tools.testers.settings import backtest_setting_registry

from . import sft_bp


def _kind_by_class() -> dict[type, Any]:
    """instance_class → page_runtime.PageObjectKind。

    建表放在函数里惰性求值，避免模块导入期的循环依赖；条目少，开销可忽略。
    """
    mapping: dict[type, Any] = {}
    from tools.products.product_path_selection import ProductPathSelection
    mapping[ProductPathSelection] = page_runtime.PRODUCT_SELECTION
    try:  # Category 目前可能尚未注册活对象，但映射先备好
        from tools.products.categories.Category import Category
        mapping[Category] = page_runtime.CATEGORY
    except Exception:
        pass
    return mapping


def _resolve_class(instance_class: Any) -> Optional[type]:
    """instance_class 可为类对象或点分路径字符串。"""
    if instance_class is None:
        return None
    if isinstance(instance_class, str):
        module_path, _, name = instance_class.rpartition(".")
        if not module_path:
            return None
        return getattr(importlib.import_module(module_path), name, None)
    return instance_class


def _serialize_instance(obj: Any) -> dict[str, Any]:
    """通用序列化一个活对象：优先用其自带的 dict 视图，再补产品摘要与类型信息。"""
    info: dict[str, Any] = {
        "type": type(obj).__name__,
        "doc": (type(obj).__doc__ or "").strip(),
    }
    for method in ("to_submission_dict", "to_dict", "describe"):
        fn = getattr(obj, method, None)
        if callable(fn):
            try:
                info["fields"] = fn()
                break
            except Exception:
                continue
    products = getattr(obj, "products", None)
    if products is not None and not callable(products):
        names = [str(getattr(p, "name", p)) for p in products]
        info["products"] = names
        info["product_count"] = len(names)
    return info


@sft_bp.get(
    "/api/test-authoring/modules/<application>/fields/<key>/instance-info"
)
@login_required
def get_setting_instance_info(application: str, key: str):
    page_uuid = (request.args.get("page_uuid") or "").strip()
    value_id = (request.args.get("id") or request.args.get("value") or "").strip()
    if not page_uuid:
        return jsonify({"success": False, "error": "缺少 page_uuid"}), 400
    if page_runtime.get_page_owner(page_uuid) != current_user():
        return jsonify({"success": False, "error": "page_uuid 不属于当前用户"}), 403

    try:
        app = backtest_setting_registry.get(application)
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404

    setting = app.settings.get(key)
    if setting is None:
        return jsonify({"success": False, "error": f"未知设置: {key}"}), 404
    if setting.instance_class is None:
        return jsonify({"success": True, "available": False, "reason": "该设置未声明 instance_class"})

    cls = _resolve_class(setting.instance_class)
    kind = _kind_by_class().get(cls) if cls is not None else None
    if kind is None:
        return jsonify({"success": True, "available": False, "reason": "未注册的实例类型"})

    obj = page_runtime.find_page_object(kind, value_id, page_uuid=page_uuid)
    if obj is None:
        return jsonify({"success": True, "available": False, "reason": "页面上没有对应的活对象"})

    return jsonify({"success": True, "available": True, "instance": _serialize_instance(obj)})
