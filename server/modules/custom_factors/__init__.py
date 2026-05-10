"""Custom factor blueprint assembly."""

from flask import Blueprint

cf_bp = Blueprint('custom_factors', __name__, url_prefix='/custom-factors')


from server.modules.custom_factors import catalog_routes, crud_routes, editor_routes, param_config_routes  # noqa: E402,F401
