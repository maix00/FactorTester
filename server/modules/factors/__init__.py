"""Factor candidate, instance-management, and data-query routes."""
from flask import Blueprint

factors_bp = Blueprint('factors', __name__)


def register_routes() -> None:
    from . import candidates, data  # noqa: F401
