"""Contract checks for native NautilusTrader result publication."""

from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path

import pytest
from flask import Flask

from server.services.nautilus_bridge import reports
from server.services.nautilus_bridge.version import NAUTILUS_VERSION
from server.modules.nautilus_workbench import nautilus_workbench_bp


class _Report:
    def __init__(self, body: str):
        self.body = body

    def to_csv(self, path: Path) -> None:
        Path(path).write_text(self.body, encoding="utf-8")


class _Engine:
    def generate_orders_report(self):
        return _Report("id,status\n1,FILLED\n")

    def generate_fills_report(self):
        return _Report("id,commission\n1,2 CNY\n")

    def generate_positions_report(self):
        return _Report("id,pnl\n1,10 CNY\n")

    def generate_account_report(self, *, venue):
        assert venue == "CFFEX"
        return _Report("time,free,margins\n1,100,50\n")


def _stub_visualization(monkeypatch, *, html: str = "<html>native</html>"):
    analysis = types.ModuleType("nautilus_trader.analysis")

    def create_tearsheet(*, engine, output_path):
        assert isinstance(engine, _Engine)
        Path(output_path).write_text(html, encoding="utf-8")

    analysis.create_tearsheet = create_tearsheet
    monkeypatch.setitem(sys.modules, "nautilus_trader", types.ModuleType("nautilus_trader"))
    monkeypatch.setitem(sys.modules, "nautilus_trader.analysis", analysis)
    monkeypatch.setattr(reports.metadata, "version", lambda _: NAUTILUS_VERSION)


def test_native_reports_are_published_with_verified_receipt(tmp_path, monkeypatch):
    _stub_visualization(monkeypatch)
    output = tmp_path / "job" / "nautilus"

    receipt = reports.export_backtest_reports(_Engine(), output, venue="CFFEX")

    assert receipt["engine_version"] == NAUTILUS_VERSION
    assert {item["name"] for item in receipt["artifacts"]} == {
        "tearsheet.html", "orders.csv", "fills.csv", "positions.csv", "account.csv"
    }
    assert json.loads((output / "nautilus_receipt.json").read_text()) == receipt
    for item in receipt["artifacts"]:
        body = (output / item["name"]).read_bytes()
        assert len(body) == item["size_bytes"]
        assert hashlib.sha256(body).hexdigest() == item["sha256"]
    assert "margins" in (output / "account.csv").read_text()


def test_failed_export_does_not_expose_partial_results(tmp_path, monkeypatch):
    _stub_visualization(monkeypatch, html="x" * 100)
    output = tmp_path / "nautilus"

    with pytest.raises(ValueError, match="per-artifact limit"):
        reports.export_backtest_reports(_Engine(), output, venue="CFFEX", max_artifact_bytes=20)

    assert not output.exists()


def test_account_scope_and_existing_destination_are_rejected(tmp_path, monkeypatch):
    _stub_visualization(monkeypatch)
    output = tmp_path / "nautilus"
    with pytest.raises(ValueError, match="venue is required"):
        reports.export_backtest_reports(_Engine(), output, venue=None)
    output.mkdir()
    with pytest.raises(FileExistsError):
        reports.export_backtest_reports(_Engine(), output, venue="CFFEX")


def test_capability_endpoint_requires_session_and_does_not_claim_live_support():
    app = Flask(__name__)
    app.secret_key = "test-only"
    app.register_blueprint(nautilus_workbench_bp)
    client = app.test_client()
    assert client.get("/api/nautilus/capabilities").status_code == 401

    with client.session_transaction() as session:
        session["username"] = "test-user"
    result = client.get("/api/nautilus/capabilities")
    assert result.status_code == 200
    assert result.json["sandbox"]["available"] is False
    assert result.json["live"]["available"] is False
