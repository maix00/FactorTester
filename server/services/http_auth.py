"""HTTP-level authentication helpers for Flask routes."""

from __future__ import annotations

from functools import wraps

from flask import jsonify

from server.services.session_runtime import current_user


def login_required(func):
    @wraps(func)
    def decorated(*args, **kwargs):
        if not current_user():
            # The business service is API-only.  Manager 7998 owns the login
            # shell, so a direct service-port request must never redirect to
            # a removed browser page.
            return jsonify({'success': False, 'error': '请先登录', 'login_required': True}), 401
        return func(*args, **kwargs)
    return decorated
