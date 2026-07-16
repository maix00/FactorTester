"""
Flask 应用工厂模块。

create_app() 负责：
  1. 设置模板/静态文件路径（开发模式和 PyInstaller 打包模式自适应）
  2. 设置 session secret key 和过期时间（30天）
  3. 注册所有 Blueprint（auth / core / templates / shared / sft / mfa / cn_futures / cf / admin）
"""
import sys, os
from datetime import timedelta
from flask import Flask
from server.services.sqlite_web_mount import mount_sqlite_web


def create_app() -> Flask:
    """
    创建并配置 Flask 应用。

    自动解析项目根目录（server/ 的父级），支持：
      - 开发模式：__file__ 指向源码文件
      - 打包模式：sys.frozen 为 True 时使用 PyInstaller 的 _MEIPASS
    """
    # Project root is one level above this package (server/)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if getattr(sys, 'frozen', False):
        root = getattr(sys, '_MEIPASS', os.path.abspath('.'))
    app = Flask(
        __name__,
        template_folder=os.path.join(root, 'templates'),
        static_folder=os.path.join(root, 'static'),
    )

    # 每次生成新的密钥（不持久化）
    secret_key = os.environ.get('FLASK_SECRET_KEY')
    if not secret_key:
        secret_key = os.urandom(24)
    app.secret_key = secret_key
    app.permanent_session_lifetime = timedelta(days=30)
    app.json.ensure_ascii = False

    # ── 启动时一次性建好所有 SQLite schema（避免每个 API 请求重复检查） ──
    from tools.data.account_manage import ensure_account_manager_sqlite_store
    from server.services.test_job_store import ensure_test_job_store
    from server.services.research_configurations import ensure_schema as ensure_research_configuration_schema
    from server.services.view_leases import start_lease_janitor
    ensure_account_manager_sqlite_store()
    ensure_test_job_store()
    ensure_research_configuration_schema()
    start_lease_janitor()

    # ── 注册 Blueprint ──
    from server.auth import auth_bp
    from server.core import core_bp
    from server.modules.templates import templates_bp
    from server.modules.shared import shared_bp
    from server.modules.shared import register_routes as register_shared_routes
    from server.modules.factors import factors_bp
    from server.modules.factors import register_routes as register_factor_routes
    from server.modules.single_factor_test import sft_bp
    from server.modules.products.cn_futures import cn_futures_bp
    from server.modules.custom_factors import cf_bp
    from server.modules.custom_factors import register_routes as register_custom_factor_routes
    from server.admin import admin_bp

    register_shared_routes()
    register_factor_routes()
    register_custom_factor_routes()

    app.register_blueprint(auth_bp)
    app.register_blueprint(core_bp)
    app.register_blueprint(templates_bp)
    app.register_blueprint(shared_bp)
    app.register_blueprint(factors_bp)
    app.register_blueprint(sft_bp)
    app.register_blueprint(cn_futures_bp)
    app.register_blueprint(cf_bp)
    app.register_blueprint(admin_bp)

    mount_sqlite_web(app)

    return app
