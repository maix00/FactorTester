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

    product = SimpleNamespace(get_parent_product=lambda: SimpleNamespace(
        get_contract_list=lambda start, end: [
            {"uid": "CFFEX|F|T|2403", "start_ts": 1700611200000, "end_ts": 1708387200000},
        ],
    ))
    monkeypatch.setattr(catalog_staging, "find_contract_product", lambda uid: product)
    monkeypatch.setattr(catalog_staging, "cn_futures_trading_spec_fields",
                        lambda product: {"point_value": 10000, "min_tick": 0.005,
                                         "long_margin_ratio": 0.02, "short_margin_ratio": 0.02,
                                         "trading_spec_source": "test"})
    monkeypatch.setattr(catalog_staging, "contract_data_path_for",
                        lambda uid, product: "/data/T2403.parquet")
    monkeypatch.setattr(catalog_staging, "build_contract_spec",
                        lambda uid, **kwargs: SimpleNamespace(
                            activation_ns=1700611200000000000,
                            expiration_ns=1708473600000000000,
                        ))
    captured = {}
    monkeypatch.setattr(catalog_staging, "stage_contract_minute_catalog",
                        lambda source, target, **kwargs: captured.update(
                            source=source, target=str(target), **kwargs))
    result = catalog_staging.stage_run_spec_catalogs(
        staging_requests=[{"paths": ["CFFEX|F|T|2403"]}],
        source_key="LocalCNFuturesContractMIN1", frequency="MIN1",
        start_utc="2024-01-02T00:00:00Z", end_utc="2024-01-03T00:00:00Z",
        target_root=tmp_path,
    )
    assert result["T"]["contract_uid"] == "CFFEX|F|T|2403"
    assert captured["target"].endswith("CFFEX_F_T_2403")
    assert captured["contract_uid"] == "CFFEX|F|T|2403"
