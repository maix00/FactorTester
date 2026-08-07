"""Build the Manager-owned sqlite-web sub-application.

The returned Flask application is embedded by the 7998 Manager adapter.  A
business service must not mount it into its own WSGI application: database
ownership and the tab shell both belong to Manager.
"""
from __future__ import annotations

from flask import redirect, session

from server.services.local_sql_data import iter_stores
from tools.data.sqlite.bootstrap import ensure_unified_sqlite_store


_mounted_app = None
_login_hook_registered = False


def build_sqlite_web_app(secret_key):
    """Return the configured sqlite-web Flask app."""
    global _mounted_app, _login_hook_registered
    if _mounted_app is not None:
        return _mounted_app

    from sqlite_web.sqlite_web import app as sqlite_web_app
    from sqlite_web.sqlite_web import initialize_app

    ensure_unified_sqlite_store()

    db_paths = [store.path() for store in iter_stores()]
    initialize_app(db_paths, read_only=True)
    sqlite_web_app.secret_key = secret_key

    # DispatcherMiddleware bypasses the parent app's before_request hooks.
    # Register the Manager projection before the login guard so an embedded
    # 7998 request is authenticated before sqlite-web checks session state.
    from server.services.manager_gateway_auth import install_manager_gateway_auth
    install_manager_gateway_auth(sqlite_web_app)

    if not _login_hook_registered:
        @sqlite_web_app.before_request
        def _require_shared_login():
            if session.get('username'):
                return None
            return redirect('/?next=/sqlite-web/')

        _login_hook_registered = True

    _mounted_app = sqlite_web_app
    return _mounted_app
