"""HTTP-level authentication helpers for Flask routes."""

from __future__ import annotations

from functools import wraps

from flask import jsonify, redirect, request

from server.services.session_runtime import current_user


def login_required(func):
    @wraps(func)
    def decorated(*args, **kwargs):
        if not current_user():
            wants_json = (
                request.is_json
                or request.method != 'GET'
                or request.accept_mimetypes.best == "application/json"
            )
            if wants_json:
                return jsonify({'success': False, 'error': '请先登录', 'login_required': True}), 401
            return redirect('/login')
        return func(*args, **kwargs)
    return decorated
