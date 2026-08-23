"""Legacy Flask entry pages; technical docs are owned by Manager 7998."""

from flask import Blueprint, current_app, jsonify, render_template

core_bp = Blueprint("core", __name__)


@core_bp.route("/favicon.svg", methods=["GET"])
@core_bp.route("/favicon.ico", methods=["GET"])
def favicon():
    return current_app.send_static_file("favicon.svg")


@core_bp.route("/", methods=["GET"])
def home():
    return render_template("home.html")


@core_bp.route("/products", methods=["GET"])
def products():
    return render_template("products.html")


@core_bp.route("/jobs", methods=["GET"])
def jobs():
    return render_template("jobs.html")


@core_bp.route("/jobs/<job_id>", methods=["GET"])
def job_detail(job_id):
    return render_template("job_detail.html", job_id=job_id)


@core_bp.route("/local-data", methods=["GET"])
@core_bp.route("/api/local-data/stores", methods=["GET"])
@core_bp.route("/api/local-data/<store_key>/tables", methods=["GET"])
@core_bp.route("/api/local-data/<store_key>/table/<table_name>", methods=["GET"])
def local_data(**_kwargs):
    return jsonify({
        "success": False,
        "error": "database is managed by Manager 7998",
        "manager_only": True,
    }), 410
