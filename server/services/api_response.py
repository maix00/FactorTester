"""API 统一响应格式和错误处理的装饰器。

所有业务路由通过这两个函数构造响应：
  api_ok(payload, status_code)  → {"success": true, ...payload}
  api_fail(error, status_code)  → {"success": false, "error": "..."}

route_guard 装饰器自动捕获路由函数中的未处理异常，转为 api_fail 响应，
避免前端收到 HTML 500 页面。
"""

from __future__ import annotations

from functools import wraps
import json

from flask import Response


def api_ok(payload: dict | None = None, status_code: int = 200):
    """构造成功响应 {'success': True, ...payload}"""
    body = {'success': True}
    if payload:
        body.update(payload)
    data = json.dumps(body, ensure_ascii=False, separators=(',', ':'))
    return Response(data, status=status_code, content_type='application/json; charset=utf-8')


def api_fail(error: str, status_code: int = 200):
    """构造失败响应 {'success': False, 'error': str}"""
    data = json.dumps({'success': False, 'error': str(error)}, ensure_ascii=False, separators=(',', ':'))
    return Response(data, status=status_code, content_type='application/json; charset=utf-8')


def route_guard(func):
    """装饰器：捕获路由函数中未处理的异常，转为 api_fail 响应。"""

    @wraps(func)
    def _wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            return api_fail(str(exc))

    return _wrapper
