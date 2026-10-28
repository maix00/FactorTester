"""Source-owned China futures meanings are visible without contract enumeration."""

from __future__ import annotations

from types import SimpleNamespace

from sources.registry import load_all_sources
from tools.data.source_catalog import data_source_declarations


def _members():
    load_all_sources()
    return {
        member.key: member
        for declaration in data_source_declarations()
        for member in declaration.members
    }


def test_all_four_local_futures_feeds_are_declared_without_contract_listing(monkeypatch):
    from sources.LocalCNFutures import CNFutures as source

    original_listdir = source.os.listdir

    def fail_contract_listing(path):
        if str(path).endswith("data_mink_product"):
            raise AssertionError("source declaration enumerated contract files")
        return original_listdir(path)

    monkeypatch.setattr(source.os, "listdir", fail_contract_listing)
    members = _members()
    assert {
        "LocalCNFuturesMIN1", "LocalCNFuturesDAY1",
        "LocalCNFuturesContractMIN1", "LocalCNFuturesContractDAY1",
    }.issubset(members)
    assert members["LocalCNFuturesMIN1"].instrument_scope == "continuous_signal"
    assert members["LocalCNFuturesContractMIN1"].instrument_scope == "physical_contract"
    assert members["LocalCNFuturesMIN1"].bar_time_semantics == "interval_end"
    assert members["LocalCNFuturesContractDAY1"].bar_time_semantics == "trading_day_label"
    assert all(members[key].raw_timestamp_unit == "ms" for key in (
        "LocalCNFuturesMIN1", "LocalCNFuturesContractMIN1",
    ))
    assert all(members[key].raw_timestamp_unit == "date_label" for key in (
        "LocalCNFuturesDAY1", "LocalCNFuturesContractDAY1",
    ))
    assert members["LocalCNFuturesContractDAY1"].data_columns[
        "SETTLEMENT_PRICE"
    ] == "SETTLEMENT_PRICE"


def test_asset_class_is_source_owned_and_unknowns_fail_closed():
    members = _members()
    for member in members.values():
        assert member.asset_class_for_product(SimpleNamespace(name="T.CFE")) == "DEBT"
        assert member.asset_class_for_product(SimpleNamespace(name="CFFEX|F|TL|2506")) == "DEBT"
        assert member.asset_class_for_product(SimpleNamespace(name="IF.CFE")) == "EQUITY"
        assert member.asset_class_for_product(SimpleNamespace(name="AU.SHF")) == "COMMODITY"
        assert member.asset_class_for_product(SimpleNamespace(name="SHFE|F|AU|2510")) == "COMMODITY"
        assert member.asset_class_for_product(SimpleNamespace(name="UNKNOWN.CFE")) is None
        assert member.asset_class_for_product(SimpleNamespace(name="UNKNOWN.XYZ")) is None


def test_registered_contract_day1_feed_has_a_verified_adapter_without_file_probes():
    from server.services.nautilus_bridge.source_registry import from_server_sources

    registry = from_server_sources()
    capabilities = {row.member_key: row for row in registry.capabilities()}
    daily = capabilities["LocalCNFuturesContractDAY1"]
    assert daily.adapter_id == "local_cnfutures_contract_daily_term_structure_v1"
    assert daily.raw_timestamp_unit == "date_label"
    assert daily.reason == ""


def test_field_history_is_lazy_strict_historical_and_preserves_raw_mapping(monkeypatch):
    from tools.data import field_history

    member = _members()["LocalCNFuturesContractMIN1"]
    assert member.trading_field_provider_ref == "FieldHistory:market_rules:exchange"
    assert member.trading_field_effective_clock == "effective_timestamp_or_trading_day"
    assert member.time_columns["trade_time"] == "MIN1"
    assert member.data_columns["trade_timestamp"] == "TIMESTAMP"
    calls = []
    sentinel = object()
    monkeypatch.setattr(field_history, "load_market_rule_field_provider", lambda **kwargs: (
        calls.append(kwargs), sentinel,
    )[-1])
    assert member.load_trading_field_provider() is sentinel
    assert calls == [{
        "include_openctp_latest": False, "transaction_fee_source": "exchange",
    }]


def test_rule_provider_can_use_caller_owned_frame_without_store_reader(monkeypatch):
    from tools.data import field_history

    frame = field_history.load_historical_field_frame()
    monkeypatch.setattr(
        field_history, "load_historical_field_frame",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must use caller frame")),
    )
    provider = field_history.load_market_rule_field_provider(frame=frame)
    assert provider.frame is not None


def test_strict_rule_provider_is_cached_per_sqlite_revision(monkeypatch):
    from tools.data import field_history
    from sources.LocalCNFutures import CNFutures

    calls = []
    monkeypatch.setattr(CNFutures, "_rule_revision_for", lambda conn, path: (1, 1))
    monkeypatch.setattr(
        field_history, "load_market_rule_field_provider",
        lambda **kwargs: (calls.append(kwargs), object())[-1],
    )
    CNFutures._clear_rule_provider_cache()
    try:
        first = CNFutures._strict_exchange_field_history()
        assert CNFutures._strict_exchange_field_history() is first
        assert len(calls) == 1
        monkeypatch.setattr(CNFutures, "_rule_revision_for", lambda conn, path: (2, 2))
        assert CNFutures._strict_exchange_field_history() is not first
        assert len(calls) == 2
    finally:
        CNFutures._clear_rule_provider_cache()


def test_new_server_source_is_projected_without_special_casing(monkeypatch):
    from tools.data.source_catalog import (
        DataSourceDeclaration,
        DataSourceMember,
        DataSourceMode,
        register_data_source,
    )

    member = DataSourceMember(
        key="SyntheticQUOTE", label="Synthetic quote",
        supports=lambda product: True, available=lambda product: False,
        mode=DataSourceMode(
            key="quote", title_zh="行情报价", sampling_mode="event",
            frequency=None, data_kind="quote", market_depth="l1",
            delivery_mode="historical_snapshot",
        ),
    )
    declaration = DataSourceDeclaration(
        key="SyntheticForTest", label="Synthetic", provider_kind="test",
        member_loader=lambda: (member,),
    )
    register_data_source(declaration)
    try:
        assert "SyntheticQUOTE" in _members()
    finally:
        # Existing registry has no unregister API; restore only this test key.
        from tools.data import source_catalog
        source_catalog._DECLARATIONS.pop("SyntheticForTest", None)


def test_rule_revision_tracks_commits_and_database_path(monkeypatch, tmp_path):
    import sqlite3
    from tools.data import field_history, hub
    from sources.LocalCNFutures import CNFutures

    db = tmp_path / "rules.sqlite"
    table = field_history.HISTORICAL_FIELD_TABLE
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        field_history.ensure_historical_field_schema(conn)
        conn.execute(
            f'INSERT INTO "{table}" (provider, source_key, instrument, instrument_type, '
            "field_name, effective_trading_day, value, value_type, contract_codes) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("p", "s", "AU", "future", "PriceTick", "2025-01-01", "1", "number", "[]"),
        )
        conn.commit()

    class FakeHub:
        def get_store_path(self, key):
            assert key == "openctp"
            return db

        def connect_store(self, key):
            assert key == "openctp"
            connection = sqlite3.connect(db)
            connection.row_factory = sqlite3.Row
            return connection

    monkeypatch.setattr(hub.DataHub, "get_instance", classmethod(lambda cls: FakeHub()))
    first = CNFutures._rule_store_revision()
    with sqlite3.connect(db) as conn:
        conn.execute(
            f'INSERT INTO "{table}" (provider, source_key, instrument, instrument_type, '
            "field_name, effective_trading_day, value, value_type, contract_codes) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("p", "s2", "AU", "future", "PriceTick", "2025-01-02", "2", "number", "[]"),
        )
        conn.commit()
    second = CNFutures._rule_store_revision()
    assert first is not None and second is not None
    assert first[0] == db.resolve().as_posix()
    assert first != second


def test_strict_provider_loads_one_caller_owned_frame_per_revision(monkeypatch, tmp_path):
    from tools.data import field_history, hub
    from sources.LocalCNFutures import CNFutures

    db = tmp_path / "rules.sqlite"

    class FakeHub:
        def get_store_path(self, key):
            return db

        def connect_store(self, key):
            return _FakeConnection()

    class _FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, *args):
            return self

        def rollback(self):
            return None

    frame = field_history.pd.DataFrame()
    monkeypatch.setattr(hub.DataHub, "get_instance", classmethod(lambda cls: FakeHub()))
    monkeypatch.setattr(CNFutures, "_rule_revision_for", lambda conn, path: (1, 1))
    monkeypatch.setattr(field_history, "ensure_historical_field_schema", lambda conn: None)
    monkeypatch.setattr(field_history, "load_historical_field_frame",
                        lambda **kwargs: frame)
    frames = []
    sentinel = object()
    monkeypatch.setattr(
        field_history, "load_market_rule_field_provider",
        lambda **kwargs: (frames.append(kwargs["frame"]), sentinel)[-1],
    )
    CNFutures._clear_rule_provider_cache()
    try:
        assert CNFutures._strict_exchange_field_history() is sentinel
        assert CNFutures._strict_exchange_field_history() is sentinel
        assert len(frames) == 1 and frames[0] is frame
        monkeypatch.setattr(CNFutures, "_rule_revision_for", lambda conn, path: (2, 2))
        assert CNFutures._strict_exchange_field_history() is sentinel
        assert len(frames) == 2
    finally:
        CNFutures._clear_rule_provider_cache()


def test_rule_revision_snapshot_distinguishes_old_and_new_connections(tmp_path):
    import sqlite3
    from pathlib import Path
    from tools.data import field_history
    from sources.LocalCNFutures.CNFutures import _rule_revision_for

    db = tmp_path / "rules.sqlite"
    table = field_history.HISTORICAL_FIELD_TABLE
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        field_history.ensure_historical_field_schema(conn)
        conn.execute(
            f'INSERT INTO "{table}" (provider, source_key, instrument, instrument_type, '
            "field_name, effective_trading_day, value, value_type, contract_codes) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("p", "old", "AU", "future", "PriceTick", "2025-01-01", "1", "number", "[]"),
        )
        conn.commit()
    old = sqlite3.connect(db)
    old.row_factory = sqlite3.Row
    old.execute("BEGIN")
    old_revision = _rule_revision_for(old, Path(db))
    with sqlite3.connect(db) as new:
        new.execute(
            f'INSERT INTO "{table}" (provider, source_key, instrument, instrument_type, '
            "field_name, effective_trading_day, value, value_type, contract_codes) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("p", "new", "AU", "future", "PriceTick", "2025-01-02", "2", "number", "[]"),
        )
        new.commit()
    new_revision = _rule_revision_for(sqlite3.connect(db), Path(db))
    old.rollback()
    old.close()
    assert old_revision != new_revision


def test_strict_provider_loading_is_single_flight(monkeypatch, tmp_path):
    import threading
    import time
    from tools.data import field_history, hub
    from sources.LocalCNFutures import CNFutures

    class FakeConnection:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, *args): return self
        def rollback(self): return None

    class FakeHub:
        def get_store_path(self, key): return tmp_path / "rules.sqlite"
        def connect_store(self, key): return FakeConnection()

    monkeypatch.setattr(hub.DataHub, "get_instance", classmethod(lambda cls: FakeHub()))
    monkeypatch.setattr(CNFutures, "_rule_revision_for", lambda conn, path: (1,))
    monkeypatch.setattr(field_history, "ensure_historical_field_schema", lambda conn: None)
    monkeypatch.setattr(field_history, "load_historical_field_frame", lambda **kwargs: object())
    calls = []
    sentinel = object()
    def load(**kwargs):
        calls.append(1)
        time.sleep(0.05)
        return sentinel
    monkeypatch.setattr(field_history, "load_market_rule_field_provider", load)
    CNFutures._clear_rule_provider_cache()
    results = []
    threads = [threading.Thread(target=lambda: results.append(CNFutures._strict_exchange_field_history())) for _ in range(2)]
    try:
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        assert calls == [1]
        assert results == [sentinel, sentinel]
    finally:
        CNFutures._clear_rule_provider_cache()


def test_rule_revision_query_uses_primary_key_not_history_scan(tmp_path):
    import sqlite3
    from tools.data import field_history

    db = tmp_path / "rules.sqlite"
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        field_history.ensure_historical_field_schema(conn)
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT revision FROM historical_field_revision WHERE id = 1"
        ).fetchall()
    detail = " ".join(str(row["detail"]) for row in plan)
    assert "historical_field_values" not in detail
    assert "SEARCH" in detail.upper()
