"""Template management blueprint assembly."""

from flask import Blueprint

templates_bp = Blueprint('templates', __name__)

from server.modules.products import product_group_routes  # noqa: E402,F401
