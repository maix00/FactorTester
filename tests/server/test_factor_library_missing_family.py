"""A registration whose family is gone must answer 404, not an HTML 500.

Configs can outlive the family source they were frozen from.  The create path
used to raise ImportError out of the view, so the caller saw a 500 error page
and could not tell a missing family from a broken server.
"""

from __future__ import annotations

import contextlib

from flask import Flask

from server.modules.custom_factors import factor_library_routes as routes


def _view():
    view = routes.api_add_factor_to_library_config
    return getattr(view, "__wrapped__", view)


def test_missing_family_returns_404(monkeypatch):
    monkeypatch.setattr(routes, "_username", lambda: "alice")
    if hasattr(routes, "get_user_file_lock"):
        monkeypatch.setattr(routes, "get_user_file_lock", lambda u: contextlib.nullcontext())

    def boom(*args, **kwargs):
        raise ImportError(
            "Cannot load factor 'TW': not found in custom factor library for user 'alice'"
        )

    monkeypatch.setattr(routes, "save_single_library_factor", boom)
    app = Flask(__name__)
    with app.test_request_context(
        "/api/factor-library/configurations/TW/factors",
        method="POST",
        json={"params": {"$F": "1m"}},
    ):
        body, code = _view()("TW")
    assert code == 404
    assert "TW" in body.get_json()["error"]
