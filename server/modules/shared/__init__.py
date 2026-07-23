from flask import Blueprint

shared_bp = Blueprint('shared', __name__)

def register_routes() -> None:
    from . import (  # noqa: F401
        data_availability,
        client_releases,
        factor_param_resolver,
        page_lifecycle,
        price_data,
        product_liquidity,
        protocol_manifest,
        submissions,
        time_range,
    )
