from __future__ import annotations

import hashlib

from flask import Flask

from server.modules.single_factor_test import sft_bp
from server.modules.single_factor_test import run_input_routes


def _app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "run-input-inspection"
    app.register_blueprint(sft_bp)
    return app


def _login(client) -> None:
    with client.session_transaction() as session:
        session["username"] = "alice"


def test_strategy_inspection_returns_callbacks_and_normalized_spec() -> None:
    client = _app().test_client()
    _login(client)
    source = "\n".join((
        "from tools.testers.backtest.engines.native.strategy import Strategy",
        "class IntradayHook(Strategy):",
        "    def on_bar(self, ctx, bar):",
        "        return None",
        "    def on_order_filled(self, ctx, order):",
        "        return None",
        "",
    ))

    response = client.post(
        "/api/run-inputs/strategy/inspect",
        json={
            "path": "strategies/intraday_hook.py",
            "source_code": source,
            "entrypoint": "IntradayHook",
            "strategy_spec": {
                "source": "profile:strategies/intraday_hook.py",
                "strategy_id": "intraday_hook",
                "entrypoint": "IntradayHook",
                "parameters": {"threshold": 0.2},
            },
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["valid"] is True
    assert payload["entrypoint"] == "IntradayHook"
    assert payload["callbacks"] == ["on_bar", "on_order_filled"]
    assert payload["hooks"][0]["name"] == "on_bar"
    assert payload["hooks"][1]["name"] == "on_order_filled"
    assert payload["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert payload["source_bytes"] == len(source.encode())
    assert payload["requirements"] == {}
    assert payload["strategy_spec"]["source"] == "profile:strategies/intraday_hook.py"
    assert payload["strategy_spec"]["parameters"] == {"threshold": 0.2}


def test_strategy_inspection_rejects_source_without_strategy_subclass() -> None:
    client = _app().test_client()
    _login(client)

    response = client.post(
        "/api/run-inputs/strategy/inspect",
        json={
            "path": "strategies/not_a_strategy.py",
            "source_code": "class NotAStrategy:\n    pass\n",
        },
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "invalid_strategy_source"


def test_strategy_inspection_uses_inherited_callbacks() -> None:
    client = _app().test_client()
    _login(client)
    source = """from tools.testers.backtest.engines.native.strategy import Strategy

class Base(Strategy):
    def on_bar(self, ctx, bar):
        return None

class Child(Base):
    def on_order_filled(self, ctx, order):
        return None
"""
    response = client.post(
        "/api/run-inputs/strategy/inspect",
        json={
            "path": "strategies/inherited.py",
            "source_code": source,
            "entrypoint": "Child",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["entrypoint"] == "Child"
    assert payload["callbacks"] == ["on_bar", "on_order_filled"]
    assert [hook["name"] for hook in payload["hooks"]] == ["on_order_filled"]
