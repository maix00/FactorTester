"""Mount and configure the sqlite-web sub-application."""
from __future__ import annotations

from flask import redirect, session
from werkzeug.middleware.dispatcher import DispatcherMiddleware

from server.services.local_sql_data import iter_stores
from tools.data.sqlite.bootstrap import ensure_unified_sqlite_store


_mounted_app = None


def build_sqlite_web_app(secret_key):
    """Return the configured sqlite-web Flask app."""
    global _mounted_app
    if _mounted_app is not None:
        return _mounted_app

    from sqlite_web.sqlite_web import app as sqlite_web_app
    from sqlite_web.sqlite_web import initialize_app

    ensure_unified_sqlite_store()

    db_paths = [store.path() for store in iter_stores()]
    initialize_app(db_paths, read_only=True)
    sqlite_web_app.secret_key = secret_key

    @sqlite_web_app.before_request
    def _require_shared_login():
        if session.get('username'):
            return None
        return redirect('/?next=/sqlite-web/')

    _mounted_app = sqlite_web_app
    return _mounted_app


def mount_sqlite_web(app) -> None:
    sqlite_web_app = build_sqlite_web_app(app.secret_key)
    app.wsgi_app = DispatcherMiddleware(
        app.wsgi_app,
        {
            '/sqlite-web': sqlite_web_app.wsgi_app,
        },
    )
