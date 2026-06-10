"""Mount and configure the sqlite-web sub-application."""
from __future__ import annotations

from flask import redirect, session
from werkzeug.middleware.dispatcher import DispatcherMiddleware


_mounted_app = None


def build_sqlite_web_app(secret_key):
    """Return the configured sqlite-web Flask app."""
    global _mounted_app
    if _mounted_app is not None:
        return _mounted_app

    from sqlite_web.sqlite_web import app as sqlite_web_app
    from sqlite_web.sqlite_web import initialize_app
    from sources.OpenCTP.client import ensure_sqlite_store
    from server.services.user_sqlite import ensure_user_sqlite_store

    openctp_db = ensure_sqlite_store()
    user_db = ensure_user_sqlite_store()
    initialize_app([openctp_db, user_db], read_only=True)
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
