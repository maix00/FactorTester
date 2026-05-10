from __future__ import annotations

from functools import wraps

from flask import jsonify


def api_ok(payload: dict | None = None, status_code: int = 200):
    body = {'success': True}
    if payload:
        body.update(payload)
    return jsonify(body), status_code


def api_fail(error: str, status_code: int = 200):
    return jsonify({'success': False, 'error': str(error)}), status_code


def route_guard(func):
    """Wrap route handlers and map unexpected errors to a consistent API response."""

    @wraps(func)
    def _wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            return api_fail(str(exc))

    return _wrapper
