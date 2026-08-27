import importlib
import sys

from flask import Blueprint

shared_bp = Blueprint('shared', __name__)
_routes_registered = False

def register_routes() -> None:
    global _routes_registered, shared_bp
    if _routes_registered:
        return
    route_names = (
        "data_availability",
        "client_releases",
        "factor_param_resolver",
        "page_lifecycle",
        "price_data",
        "product_liquidity",
        "protocol_manifest",
        "submissions",
        "time_range",
    )
    # A few lightweight tests embed the exported blueprint directly.  If
    # that happened before the application factory ran, Flask forbids adding
    # decorators to it; use a fresh blueprint for the real app and reload the
    # route modules so every decorator targets the new object.
    if getattr(shared_bp, "_got_registered_once", False):
        shared_bp = Blueprint("shared", __name__)
    for name in route_names:
        module_name = f"{__name__}.{name}"
        module = sys.modules.get(module_name)
        if module is not None:
            importlib.reload(module)
        else:
            importlib.import_module(module_name)
    _routes_registered = True
