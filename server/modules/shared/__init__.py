from flask import Blueprint

shared_bp = Blueprint('shared', __name__)

def register_routes() -> None:
    from . import factor_param_resolver, time_range, submissions, price_data, page_lifecycle  # noqa: F401
