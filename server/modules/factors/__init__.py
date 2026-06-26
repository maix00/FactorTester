"""Factor routes: candidate/instance management, data queries, analysis runs."""
from flask import Blueprint

factors_bp = Blueprint('factors', __name__)


def register_routes() -> None:
    from . import candidates, data, analysis  # noqa: F401
