"""Custom factor blueprint assembly."""

from flask import Blueprint

cf_bp = Blueprint('custom_factors', __name__, url_prefix='/custom-factors')
factor_library_internal_bp = Blueprint(
    'factor_library_internal', __name__,
    url_prefix='/api/internal/factor-library',
)

def register_routes() -> None:
    from server.modules.custom_factors import (  # noqa: F401
        catalog_routes,
        crud_routes,
        editor_routes,
        factor_library_routes,
        source_sync_routes,
    )
