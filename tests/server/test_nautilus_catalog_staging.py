from server.services.nautilus_bridge.catalog_staging import _ns


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
