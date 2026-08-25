"""Custom factor blueprint assembly."""

from flask import Blueprint

cf_bp = Blueprint('custom_factors', __name__, url_prefix='/custom-factors')

def register_routes() -> None:
    from server.modules.custom_factors import (  # noqa: F401
        catalog_routes,
        crud_routes,
        editor_routes,
        factor_library_routes,
        source_sync_routes,
    )
