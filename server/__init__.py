"""
Flask 应用工厂模块。

create_app() 负责：
  1. 创建只提供 API 的业务服务 Flask 应用（网页由 Manager 7998 承载）
  2. 设置 session secret key 和过期时间（30天）
  3. 注册 API Blueprint（auth / templates / shared / sft / cn_futures / cf / admin）
"""
from __future__ import annotations

from datetime import timedelta


def create_app():
    """
    创建并配置 Flask 应用。

    业务端口不配置模板目录或静态目录；网页入口统一由 Manager 7998 提供。
    """
    # Keep application-only imports inside the factory. Deployment modules
    # under ``server.deployment`` must be usable before runtime .settings,
    # SQLite, Flask, or session state exists on a new host.
    from flask import Flask
    from server.services.session_secret import load_session_secret

    # Business ports are data/execution APIs only.  The Manager owns the
    # browser shell, static assets, technical docs, database browser, and all
    # module entry pages.  Disabling Flask's template/static adapters here
    # makes accidental reintroduction of a service-port web page fail closed.
    app = Flask(__name__, static_folder=None, template_folder=None)

    # 持久化 secret，避免服务器重启或客户端更新导致所有会话失效。
    app.secret_key = load_session_secret()
    app.permanent_session_lifetime = timedelta(days=30)
    app.json.ensure_ascii = False

    from server.services.manager_gateway_auth import install_manager_gateway_auth
    install_manager_gateway_auth(app)

    # ── 启动时一次性建好所有 SQLite schema（避免每个 API 请求重复检查） ──
    from tools.data.account_manage import ensure_account_manager_sqlite_store
    from server.jobs.repository import JobRepository
    from server.services.research_configurations import ensure_schema as ensure_research_configuration_schema
    from server.services.research_runs import ensure_schema as ensure_research_run_schema
    from server.services.research_graphs import ensure_schema as ensure_research_graph_schema
    ensure_account_manager_sqlite_store()
    job_repository = JobRepository()
    job_repository.ensure_schema()
    app.extensions['job_repository'] = job_repository
    ensure_research_configuration_schema()
    ensure_research_run_schema()
    ensure_research_graph_schema()

    # ── 注册 Blueprint ──
    from server.auth import auth_bp
    from server.modules.templates import templates_bp
    from server.modules.shared import register_routes as register_shared_routes
    from server.modules.factors import factors_bp
    from server.modules.factors import register_routes as register_factor_routes
    from server.modules.single_factor_test import sft_bp
    from server.modules.products.cn_futures import cn_futures_bp
    from server.modules.custom_factors import cf_bp
    from server.modules.custom_factors import register_routes as register_custom_factor_routes
    from server.admin import admin_bp
    from server.server_operations import server_operations_bp

    register_shared_routes()
    from server.modules.shared import shared_bp
    register_factor_routes()
    register_custom_factor_routes()

    app.register_blueprint(auth_bp)
    app.register_blueprint(templates_bp)
    app.register_blueprint(shared_bp)
    app.register_blueprint(factors_bp)
    app.register_blueprint(sft_bp)
    app.register_blueprint(cn_futures_bp)
    app.register_blueprint(cf_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(server_operations_bp)

    return app
