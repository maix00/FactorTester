"""Template management blueprint assembly."""

from flask import Blueprint

templates_bp = Blueprint('templates', __name__)

from server.modules.templates import path_time_routes, params_routes, setting_snapshot_routes  # noqa: E402,F401
