"""An IC/backtest run that asks for factor_series must keep the market bars.

factor_series_for_run_spec aggregates the per-factor FactorEvaluation payloads;
it used to return only {factors, series}, which silently dropped the market
series the K线/成交量/持仓量 panels are drawn from.
"""

from __future__ import annotations

from server.modules.single_factor_test import evaluation as module


class _FakeEvaluation:
    def __init__(self, payload):
        self.payload = payload

    def run(self):
        return self.payload


def _stub(monkeypatch, payload):
    """Stub the evaluator and the frozen-factor gate; the passthrough is the point."""
    monkeypatch.setattr(
        module.FactorEvaluation, "from_run_spec",
        classmethod(lambda cls, request: _FakeEvaluation(payload)),
    )
    monkeypatch.setattr(module, "require_frozen_factor", lambda raw: dict(raw))


def _record(ref="factor:v2:abc"):
    """A record complete enough for the frozen-factor identity check."""
    return {
        "ref": ref, "alias": "TsHistCmp", "owner_ref": "GTHT@MaxJJW@392452984564",
        "factor_family_alias": "TsHistCmp", "factor_family_name": "TsHistCmp",
        "identity": {"family_alias": "TsHistCmp", "params": {}},
        "factor_params": {}, "factor_dependencies": [],
        "parameter_definitions": [], "schema_version": 2,
    }


def test_market_series_survives_the_aggregator(monkeypatch):
    _stub(monkeypatch, {
        "factor": {"freq": "MIN1"},
        "series": [{"product": "T.CFE", "layer": "阈值层", "values": [1.0]}],
        "market": [{"product": "T.CFE", "freq": "MIN1", "bars": [{"close": 105.0}]}],
    })
    payload = module.factor_series_for_run_spec({"factors": [_record()]})

    assert [item["layer"] for item in payload["series"]] == ["阈值层"]
    assert payload["market"][0]["product"] == "T.CFE"
    assert payload["market"][0]["bars"] == [{"close": 105.0}]


def test_market_key_is_absent_when_no_bars_were_loaded(monkeypatch):
    _stub(monkeypatch, {"series": [{"product": "T.CFE", "values": [1.0]}]})
    payload = module.factor_series_for_run_spec({"factors": [_record()]})

    assert "market" not in payload


def test_duplicate_market_entries_are_kept_once(monkeypatch):
    same = {"product": "T.CFE", "freq": "MIN1", "bars": [{"close": 105.0}]}
    _stub(monkeypatch, {"series": [{"product": "T.CFE", "values": [1.0]}], "market": [same]})
    payload = module.factor_series_for_run_spec({"factors": [_record(), _record("factor:v2:def")]})

    assert len(payload["market"]) == 1
