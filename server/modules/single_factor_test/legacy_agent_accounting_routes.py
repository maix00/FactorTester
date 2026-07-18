"""Explicitly retired Graph-owned Agent accounting HTTP endpoints."""

from __future__ import annotations

from flask import jsonify

from server.modules.single_factor_test import sft_bp
from server.services.session_runtime import require_user


def _retired_agent_accounting_response():
    require_user()
    return jsonify({
        "success": False,
        "error": (
            "This Graph-owned accounting endpoint is retired; "
            "use /api/agent-flow endpoints."
        ),
        "replacement": "/api/agent-flow",
    }), 410


@sft_bp.post("/api/research-agent-executions")
def retired_research_agent_execution():
    return _retired_agent_accounting_response()


@sft_bp.post("/api/research-token-budgets")
def retired_research_token_budget():
    return _retired_agent_accounting_response()


@sft_bp.post("/api/research-token-budgets/<scope_id>/reserve")
def retired_research_token_reservation(scope_id: str):
    del scope_id
    return _retired_agent_accounting_response()


@sft_bp.post("/api/research-provider-usage-receipts")
def retired_research_provider_usage():
    return _retired_agent_accounting_response()


@sft_bp.post("/api/research-token-reservations/<reservation_id>/commit")
def retired_research_token_commit(reservation_id: str):
    del reservation_id
    return _retired_agent_accounting_response()


@sft_bp.post("/api/research-token-reservations/<reservation_id>/release")
def retired_research_token_release(reservation_id: str):
    del reservation_id
    return _retired_agent_accounting_response()
