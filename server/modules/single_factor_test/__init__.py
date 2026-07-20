"""
single_factor_test Blueprint package.
Registers page + ic + group sub-modules onto a single Blueprint.
"""
from flask import Blueprint

sft_bp = Blueprint('sft', __name__)

from . import (  # noqa: E402, F401
    agent_flow_routes,
    backtest_job_reads,
    backtest_jobs,
    backtest_settings,
    category_routes,
    group,
    ic,
    page,
    research_graph_routes,
    research_jobs,
    setting_instance_routes,
)
