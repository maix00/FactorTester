from flask import Blueprint

shared_bp = Blueprint('shared', __name__)

from . import params, time_range, submissions, factor_data  # noqa: E402, F401
