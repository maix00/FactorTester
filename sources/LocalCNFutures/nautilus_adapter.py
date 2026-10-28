"""Nautilus feed contracts owned by the LocalCNFutures data source.

These contracts describe only this source's physical parquet layouts and time
labels. Other data sources must declare their own adapter contracts.
"""

from traderesearch_data.nautilus import NautilusAdapterContract


CONTRACT_MIN1 = NautilusAdapterContract(
    member_key="LocalCNFuturesContractMIN1",
    adapter_id="local_cnfutures_contract_minute_parquet_v1",
    frequency="MIN1", sampling_mode="bar", data_kind="ohlcv_bar",
    market_depth="not_applicable", delivery_mode="historical_snapshot",
    timezone="Asia/Shanghai", layout="parquet_ohlcv",
    naming_scheme="local_cnfutures_contract_uid_v1",
    required_time_columns=(("trade_time", "MIN1"), ("trading_day", "DAY1")),
    required_data_columns=(
        ("trade_timestamp", "TIMESTAMP"), ("open_price", "OPEN"),
        ("highest_price", "HIGH"), ("lowest_price", "LOW"),
        ("close_price", "CLOSE"), ("volume", "VOLUME"),
        ("open_interest", "OPEN_INTEREST"),
    ),
    clock_policy="end_label_utc_ns_validated_from_exchange_wall_time",
    product_scope="physical_contract_only", instrument_scope="physical_contract",
    bar_time_semantics="interval_end", raw_timestamp_unit="ms",
    supported_book_types=("L1_MBP",),
)

CONTRACT_DAY1 = NautilusAdapterContract(
    member_key="LocalCNFuturesContractDAY1",
    adapter_id="local_cnfutures_contract_daily_term_structure_v1",
    frequency="DAY1", sampling_mode="bar", data_kind="ohlcv_bar",
    market_depth="not_applicable", delivery_mode="historical_snapshot",
    timezone="Asia/Shanghai", layout="term_structure_snapshot",
    naming_scheme="local_cnfutures_contract_uid_v1",
    required_time_columns=(("TRADING_DAY", "DAY1"),),
    required_data_columns=(
        ("OPEN", "OPEN"), ("HIGH", "HIGH"), ("LOW", "LOW"),
        ("CLOSE", "CLOSE"), ("VOLUME", "VOLUME"),
        ("OPEN_INTEREST", "OPEN_INTEREST"),
        ("SETTLEMENT_PRICE", "SETTLEMENT_PRICE"),
    ),
    clock_policy="frozen_exchange_session_close_for_trading_day_label",
    product_scope="physical_contract_only", instrument_scope="physical_contract",
    bar_time_semantics="trading_day_label", raw_timestamp_unit="date_label",
    supported_book_types=("L1_MBP",),
)


__all__ = ["CONTRACT_MIN1", "CONTRACT_DAY1"]
