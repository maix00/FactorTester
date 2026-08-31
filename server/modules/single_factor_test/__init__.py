"""
single_factor_test Blueprint package.
Registers the IC/backtest service APIs onto a single Blueprint.

The historical ``/single_factor_test`` HTML application was retired after the
IC and backtest workbenches became first-class client modules.  The execution
APIs remain here because both clients consume the same service contract.
"""
from urllib.parse import urlsplit

from flask import Blueprint, request

sft_bp = Blueprint('sft', __name__)


@sft_bp.after_request
def allow_same_host_job_reads(response):
    """Allow the Job page to aggregate authenticated sibling FactorTester ports."""
    if not request.path.startswith("/api/jobs"):
        return response
    origin = str(request.headers.get("Origin") or "")
    parsed = urlsplit(origin)
    if origin and parsed.hostname == request.host.split(":", 1)[0]:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Vary"] = "Origin"
    return response

from . import (  # noqa: F401
    agent_flow_routes,
    backtest_job_reads,
    backtest_jobs,
    backtest_settings,
    category_routes,
    configuration_snapshot_routes,
    direct_trial_routes,
    group,
    ic,
    job_port_routes,
    research_graph_routes,
    research_jobs,
    research_result_report_routes,
    research_step_routes,
    run_input_routes,
    setting_instance_routes,
    supplemental_routes,
    trial_plan_revision_routes,
)
