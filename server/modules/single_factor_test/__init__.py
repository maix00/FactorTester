"""
single_factor_test Blueprint package.
Registers ic + group sub-modules onto a single Blueprint.
"""
from flask import Blueprint

sft_bp = Blueprint('sft', __name__)

from . import ic, group  # noqa: E402, F401 – register routes
