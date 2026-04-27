from flask import Blueprint

cn_futures_bp = Blueprint('cn_futures', __name__)

from . import fee  # noqa: E402, F401
