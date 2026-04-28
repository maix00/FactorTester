import sys, os
from datetime import timedelta
from flask import Flask


def create_app() -> Flask:
    # Project root is one level above this package (server/)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if getattr(sys, 'frozen', False):
        root = getattr(sys, '_MEIPASS', os.path.abspath('.'))
    app = Flask(
        __name__,
        template_folder=os.path.join(root, 'templates'),
        static_folder=os.path.join(root, 'static'),
    )

    app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24))
    app.permanent_session_lifetime = timedelta(days=30)

    from server.auth import auth_bp
    from server.core import core_bp
    from server.templates_bp import templates_bp
    from server.modules.shared import shared_bp
    from server.modules.single_factor_test import sft_bp
    from server.modules.multi_factor_analysis import mfa_bp
    from server.modules.products.cn_futures import cn_futures_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(core_bp)
    app.register_blueprint(templates_bp)
    app.register_blueprint(shared_bp)
    app.register_blueprint(sft_bp)
    app.register_blueprint(mfa_bp)
    app.register_blueprint(cn_futures_bp)

    return app
