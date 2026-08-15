"""Authenticated user-library routes for Research Graph YAML files."""

from __future__ import annotations

from flask import Response, jsonify, request

from server.modules.single_factor_test import sft_bp
from server.services import research_graphs
from server.services.session_runtime import require_user


@sft_bp.get("/api/research-graphs/user-library")
def list_user_research_graphs():
    owner = require_user()
    return jsonify({
        "success": True,
        "files": research_graphs.list_user_graphs(owner=owner),
        "default": research_graphs.get_default_user_graph(owner=owner),
        "source_server_id": _source_server_id(),
        "sync_scope": "manager-local",
    })


@sft_bp.post("/api/research-graphs/user-library")
def upload_user_research_graph():
    owner = require_user()
    uploaded = request.files.get("file")
    if uploaded is not None:
        raw_yaml = uploaded.read(research_graphs.MAX_USER_GRAPH_YAML_BYTES + 1)
        filename = uploaded.filename or "research-graph.yaml"
        name = request.form.get("name", "")
    else:
        data = request.get_json(silent=True) or {}
        raw_yaml = data.get("yaml", "")
        filename = str(data.get("filename") or "research-graph.yaml")
        name = str(data.get("name") or "")
    try:
        value = research_graphs.upload_user_graph(
            owner=owner,
            filename=filename,
            raw_yaml=raw_yaml,
            name=name,
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({
        "success": True,
        "file": value,
        "sync_scope": "manager-local",
    }), 201


@sft_bp.get("/api/research-graphs/user-library/<graph_file_id>")
def get_user_research_graph(graph_file_id: str):
    owner = require_user()
    value = research_graphs.load_user_graph(
        owner=owner,
        graph_file_id=graph_file_id,
    )
    if value is None:
        return jsonify({"success": False, "error": "user research graph not found"}), 404
    if request.args.get("download") in {"1", "true", "yes"}:
        response = Response(
            str(value["yaml"]).encode("utf-8"),
            status=200,
            mimetype="application/yaml",
        )
        response.headers["Content-Disposition"] = (
            f'attachment; filename="{value["filename"]}"'
        )
        return response
    value.pop("yaml", None)
    value.pop("graph", None)
    return jsonify({"success": True, "file": value})


@sft_bp.delete("/api/research-graphs/user-library/<graph_file_id>")
def delete_user_research_graph(graph_file_id: str):
    owner = require_user()
    if not research_graphs.delete_user_graph(
        owner=owner,
        graph_file_id=graph_file_id,
    ):
        return jsonify({"success": False, "error": "user research graph not found"}), 404
    return jsonify({"success": True, "deleted": graph_file_id})


@sft_bp.get("/api/research-graphs/user-library/default")
def get_default_user_research_graph():
    owner = require_user()
    return jsonify({
        "success": True,
        "default": research_graphs.get_default_user_graph(owner=owner),
        "source_server_id": _source_server_id(),
        "sync_scope": "manager-local",
    })


@sft_bp.post("/api/research-graphs/user-library/default")
def set_default_user_research_graph():
    owner = require_user()
    data = request.get_json(silent=True) or {}
    try:
        value = research_graphs.set_default_user_graph(
            owner=owner,
            kind=str(data.get("kind") or "none"),
            graph_file_id=str(data.get("graph_file_id") or ""),
            graph_id=str(data.get("graph_id") or ""),
            version=int(data.get("version") or 0),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({
        "success": True,
        "default": value,
        "source_server_id": _source_server_id(),
        "sync_scope": "manager-local",
    })


def _source_server_id() -> str:
    # The Flask service is also usable without a Manager in tests/development.
    # A Manager child exports its stable identity to the service process.
    import os

    return str(os.environ.get("FACTORTESTER_SERVER_ID") or "local")
