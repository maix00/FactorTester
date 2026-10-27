from server.services.nautilus_bridge.catalog_staging import _ns


def test_staged_calendar_reuses_frozen_day_summary_without_source_access(tmp_path, monkeypatch):
    from datetime import date
    from tests.nautilus_runtime import require_nautilus
    from tests.server.test_nautilus_bridge_backtest_runner import _real_catalog
    from server.services.nautilus_bridge.catalog_staging import build_run_spec_session_calendar
    require_nautilus()
    item = _real_catalog(tmp_path, count=8)
    def forbidden(*args, **kwargs):
        raise AssertionError("calendar must not scan source prices again")
    monkeypatch.setattr("server.services.nautilus_bridge.market_data.iter_minute_bars", forbidden)
    calendar = build_run_spec_session_calendar(catalogs={"T": {
        "catalog_dir": str(item.catalog_dir), "contract_uid": item.expected_contract_uid,
    }})
    assert len(calendar.sessions) == 1
    session = calendar.sessions[0]
    assert session.trading_day == date(2024, 1, 2)
    assert session.bar_count == 8
    assert session.end_ns - session.start_ns == 8 * 60_000_000_000


def test_session_summary_keeps_aggregate_state_for_overlapping_contracts():
    from tools.factors.expr.streaming.calendar_window import TradingSessionSummary
    summary = TradingSessionSummary()
    for bar in range(10_000):
        summary.add("day", bar, bar + 1, contract="A")
    for bar in range(5_000):
        summary.add("day", bar, bar + 1, contract="B")
    assert len(summary._groups) == 2
    session, = summary.sessions()
    assert (session.start_ns, session.end_ns, session.bar_count) == (0, 10_000, 10_000)


def test_catalog_window_timestamp_is_utc():
    assert _ns("2024-01-02T00:00:00Z") == 1704153600000000000


def test_stage_run_spec_catalogs_writes_each_frozen_contract(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from server.services.nautilus_bridge import catalog_staging
    from sources.LocalCNFutures import nautilus_catalog

    product = SimpleNamespace(get_parent_product=lambda: SimpleNamespace(
        get_contract_list=lambda start, end: [
            {"uid": "CFFEX|F|T|2403", "start_ts": 1700611200000, "end_ts": 1708387200000},
        ],
    ))
    monkeypatch.setattr(nautilus_catalog, "find_contract_product", lambda uid: product)
    monkeypatch.setattr(nautilus_catalog, "cn_futures_trading_spec_fields",
                        lambda product: {"point_value": 10000, "min_tick": 0.005,
                                         "long_margin_ratio": 0.02, "short_margin_ratio": 0.02,
                                         "trading_spec_source": "test"})
    monkeypatch.setattr(nautilus_catalog, "contract_data_path_for",
                        lambda uid, product: "/data/T2403.parquet")
    monkeypatch.setattr(nautilus_catalog, "build_contract_spec",
                        lambda uid, **kwargs: SimpleNamespace(
                            activation_ns=1700611200000000000,
                            expiration_ns=1708473600000000000,
                        ))
    captured = {}
    calls = []
    def stage(source, target, **kwargs):
        calls.append(str(target))
        captured.update(source=source, target=str(target), **kwargs)
    monkeypatch.setattr(nautilus_catalog, "stage_contract_minute_catalog", stage)
    result = catalog_staging.stage_run_spec_catalogs(
        staging_requests=[{"paths": ["CFFEX|F|T|2403"]},
                          {"paths": ["CFFEX|F|T|2403"]}],
        source_key="LocalCNFuturesContractMIN1", frequency="MIN1",
        start_utc="2024-01-02T00:00:00Z", end_utc="2024-01-03T00:00:00Z",
        target_root=tmp_path,
    )
    assert result["T"]["contract_uid"] == "CFFEX|F|T|2403"
    assert captured["target"].endswith("CFFEX_F_T_2403")
    assert captured["contract_uid"] == "CFFEX|F|T|2403"
    assert len(calls) == 1


def test_stage_catalogs_rejects_multiple_contracts_for_one_product(monkeypatch, tmp_path):
    import pytest
    from types import SimpleNamespace
    from server.services.nautilus_bridge import catalog_staging
    from sources.LocalCNFutures import nautilus_catalog

    rows = [
        {"uid": "CFFEX|F|T|2403", "start_ts": 1700611200000, "end_ts": 1708387200000},
        {"uid": "CFFEX|F|T|2406", "start_ts": 1700611200000, "end_ts": 1717171200000},
    ]
    product = SimpleNamespace(get_parent_product=lambda: SimpleNamespace(
        get_contract_list=lambda start, end: rows,
    ))
    calls = []
    monkeypatch.setattr(nautilus_catalog, "find_contract_product", lambda uid: product)
    monkeypatch.setattr(nautilus_catalog, "cn_futures_trading_spec_fields",
                        lambda product: {"point_value": 10000, "min_tick": 0.005,
                                         "long_margin_ratio": 0.02, "short_margin_ratio": 0.02,
                                         "trading_spec_source": "test"})
    monkeypatch.setattr(nautilus_catalog, "contract_data_path_for",
                        lambda uid, product: f"/data/{uid.rsplit('|', 1)[-1]}.parquet")
    monkeypatch.setattr(nautilus_catalog, "build_contract_spec",
                        lambda uid, **kwargs: SimpleNamespace(
                            activation_ns=1700611200000000000,
                            expiration_ns=1708473600000000000,
                        ))
    monkeypatch.setattr(nautilus_catalog, "stage_contract_minute_catalog",
                        lambda source, target, **kwargs: calls.append(str(target)))
    with pytest.raises(ValueError, match="multiple contracts"):
        catalog_staging.stage_run_spec_catalogs(
            staging_requests=[{"paths": [row["uid"] for row in rows]}],
            source_key="LocalCNFuturesContractMIN1", frequency="MIN1",
            start_utc="2024-01-02T00:00:00Z", end_utc="2024-01-03T00:00:00Z",
            target_root=tmp_path,
        )
    assert len(calls) == 0


def test_stage_run_spec_catalogs_dispatches_day1_reader(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from server.services.nautilus_bridge import catalog_staging
    from sources.LocalCNFutures import nautilus_catalog

    parent = SimpleNamespace(
        name="T.SHFE", alias="T.SHFE",
        trading_day_sessions="09:00-11:30,13:30-15:00",
        trading_day_close_time="15:00",
        get_term_structure_path=lambda: "/data/term.parquet",
        get_contract_list=lambda start, end: [
            {"uid": "CFFEX|F|T|2403", "start_ts": 1700611200000, "end_ts": 1708387200000},
        ],
    )
    product = SimpleNamespace(get_parent_product=lambda: parent)
    captured = {}
    monkeypatch.setattr(nautilus_catalog, "find_contract_product", lambda uid: product)
    monkeypatch.setattr(nautilus_catalog, "cn_futures_trading_spec_fields",
                        lambda product: {"point_value": 10000, "min_tick": 0.005,
                                         "long_margin_ratio": 0.02, "short_margin_ratio": 0.02,
                                         "trading_spec_source": "test"})
    monkeypatch.setattr(nautilus_catalog, "build_contract_spec",
                        lambda uid, **kwargs: SimpleNamespace(
                            activation_ns=1700611200000000000,
                            expiration_ns=1708473600000000000,
                        ))
    def stage_daily(source, target, **kwargs):
        captured.update(source=str(source), target=str(target), **kwargs)
    monkeypatch.setattr(nautilus_catalog, "stage_contract_daily_catalog", stage_daily)
    result = catalog_staging.stage_run_spec_catalogs(
        staging_requests=[{"paths": ["CFFEX|F|T|2403"]}],
        source_key="LocalCNFuturesContractDAY1", frequency="DAY1",
        start_utc="2024-01-02T00:00:00Z", end_utc="2024-01-03T00:00:00Z",
        target_root=tmp_path,
    )
    assert result["T"]["contract_uid"] == "CFFEX|F|T|2403"
    from datetime import date
    assert captured["source"] == "/data/term.parquet"
    assert captured["product_codes"] == {"T.SHFE"}
    open_dt, close_dt = captured["session_for_day"](date(2024, 1, 2))
    assert (open_dt.hour, open_dt.minute) == (9, 0)
    assert (close_dt.hour, close_dt.minute) == (15, 0)


def _bundle_with_loader():
    from dataclasses import replace
    from sources.registry import installed_bundles
    bundle = installed_bundles()[0]
    member = next(item for item in bundle.members if item.id == "LocalCNFuturesContractMIN1")
    member = replace(member, id="ExampleRates", frequency="MIN15",
                     related_members=(),
                     integrations=(("nautilus_catalog", "external_rates.catalog:stage"),))
    return replace(bundle, bundle_id="external", members=(member,))


def test_staging_dispatches_source_owned_non_cn_loader(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from server.services.nautilus_bridge import catalog_staging
    bundle = _bundle_with_loader()
    monkeypatch.setattr(catalog_staging, "installed_bundles", lambda: (bundle,))
    captured = []
    result = {"EXAMPLE": {"catalog_dir": str(tmp_path), "contract_uid": "neutral:rate"}}
    def stage(**kwargs):
        captured.append(kwargs)
        return result
    def activate(name):
        assert name == "external_rates.catalog"
        return SimpleNamespace(stage=stage)
    monkeypatch.setattr(catalog_staging, "import_module", activate)
    requests = [{"paths": ["neutral:rate"]}]
    actual = catalog_staging.stage_run_spec_catalogs(
        staging_requests=requests, source_key="ExampleRates", frequency="MIN15",
        start_utc="2024-01-02T00:00:00Z", end_utc="2024-01-03T00:00:00Z",
        target_root=tmp_path)
    assert actual is result
    assert len(captured) == 1
    assert captured[0]["staging_requests"] is requests
    assert captured[0]["start_ns"] == 1704153600000000000
    assert captured[0]["target_root"] is tmp_path


def test_invalid_source_selection_never_activates_or_creates_catalog(monkeypatch, tmp_path):
    from dataclasses import replace
    import pytest
    from server.services.nautilus_bridge import catalog_staging
    bundle = _bundle_with_loader()
    member = bundle.members[0]
    inventories = [
        (), (bundle, bundle), (replace(bundle, execution_location="client"),),
        (replace(bundle, members=(replace(member, kind="historical_rules"),)),),
        (replace(bundle, members=(replace(member, frequency="DAY1"),)),),
        (replace(bundle, members=(replace(member, data_type="trade_tick"),)),),
        (replace(bundle, members=(replace(member, integrations=()),)),),
    ]
    monkeypatch.setattr(catalog_staging, "import_module",
                        lambda name: pytest.fail("invalid selection activated source"))
    target = tmp_path / "not-created"
    for inventory in inventories:
        monkeypatch.setattr(catalog_staging, "installed_bundles", lambda: inventory)
        with pytest.raises(ValueError):
            catalog_staging.stage_run_spec_catalogs(
                staging_requests=[], source_key="ExampleRates", frequency="MIN15",
                start_utc="2024-01-02T00:00:00Z", end_utc="2024-01-03T00:00:00Z",
                target_root=target)
        assert not target.exists()


def test_importing_staging_does_not_load_concrete_sources():
    import subprocess
    import sys
    from pathlib import Path
    code = """
import sys
from server.services.nautilus_bridge.catalog_staging import stage_run_spec_catalogs
assert 'server.modules.shared.price_services' not in sys.modules
assert 'server.services.nautilus_bridge.market_data' not in sys.modules
assert not any(name.startswith(('tools.', 'sources.LocalCNFutures', 'nautilus_trader.')) for name in sys.modules)
"""
    subprocess.run([sys.executable, "-S", "-c", code], check=True, capture_output=True,
                   cwd=Path(__file__).resolve().parents[2], text=True)
