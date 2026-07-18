"""
single_factor_test Blueprint package.
Registers page + ic + group sub-modules onto a single Blueprint.
"""
from flask import Blueprint

sft_bp = Blueprint('sft', __name__)

from . import agent_flow_routes, backtest_settings, page, ic, group, backtest_jobs, research_jobs, research_graph_routes, category_routes, setting_instance_routes  # noqa: E402, F401 – register routes
