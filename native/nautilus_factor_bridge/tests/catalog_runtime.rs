#![cfg(feature = "nautilus-backtest")]

use nautilus_backtest::{
    config::{BacktestDataConfig, BacktestEngineConfig, BacktestRunConfig, BacktestVenueConfig},
    node::BacktestNode,
};
use nautilus_execution::models::fee::{FeeModelAny, MakerTakerFeeModel};
use nautilus_factor_bridge::replay::attach_factor_plan;
use nautilus_model::{
    data::{Bar, BarType, NautilusDataType},
    enums::{AccountType, BookType, OmsType},
    identifiers::{InstrumentId, Symbol},
    instruments::{CryptoPerpetual, Instrument, InstrumentAny},
    types::{Currency, Price, Quantity},
};
use nautilus_persistence::backend::parquet::catalog::ParquetDataCatalog;
use std::sync::{Arc, Mutex};

#[test]
fn native_catalog_dispatches_factor_fields_across_streaming_chunks() {
    let folder = tempfile::tempdir().unwrap();
    let instrument = InstrumentAny::CryptoPerpetual(
        CryptoPerpetual::builder()
            .instrument_id(InstrumentId::from("ETHUSDT-PERP.BINANCE"))
            .raw_symbol(Symbol::from("ETHUSDT"))
            .base_currency(Currency::from("ETH"))
            .quote_currency(Currency::from("USDT"))
            .settlement_currency(Currency::from("USDT"))
            .is_inverse(false)
            .price_precision(2)
            .size_precision(3)
            .price_increment(Price::from("0.01"))
            .size_increment(Quantity::from("0.001"))
            .ts_event(0.into())
            .ts_init(0.into())
            .build()
            .unwrap(),
    );
    let bar_type: BarType = format!("{}-1-MINUTE-LAST-EXTERNAL", instrument.id())
        .parse()
        .unwrap();
    let catalog = ParquetDataCatalog::new(folder.path(), None, None, None, None);
    catalog.write_instruments(vec![instrument]).unwrap();
    let bars: Vec<_> = (0..8)
        .map(|index| {
            let price = Price::new(100.0 + index as f64, 2);
            let timestamp = 1_700_000_000_000_000_000_u64 + index * 60_000_000_000;
            Bar::new(
                bar_type,
                price,
                Price::new(110.0 + index as f64, 2),
                price,
                price,
                Quantity::new(10.0 + index as f64, 3),
                timestamp.into(),
                (timestamp + 5).into(),
            )
        })
        .collect();
    catalog
        .write_to_parquet(&bars[..3], None, None, None)
        .unwrap();
    catalog
        .write_to_parquet(&bars[3..], None, None, None)
        .unwrap();
    let venue = BacktestVenueConfig::builder()
        .name(ustr::Ustr::from("BINANCE"))
        .oms_type(OmsType::Netting)
        .account_type(AccountType::Margin)
        .book_type(BookType::L1_MBP)
        .starting_balances(vec!["1000000 USDT".into()])
        .fee_model(FeeModelAny::MakerTaker(MakerTakerFeeModel::zero()))
        .build()
        .unwrap();
    let data = BacktestDataConfig::builder()
        .data_type(NautilusDataType::Bar)
        .catalog_path(folder.path().to_str().unwrap().to_owned())
        .bar_types(vec![bar_type.to_string()])
        .build()
        .unwrap();
    let config = BacktestRunConfig::builder()
        .id("native-factor-catalog".to_owned())
        .venues(vec![venue])
        .data(vec![data])
        .chunk_size(2)
        .engine(BacktestEngineConfig {
            bypass_logging: true,
            run_analysis: false,
            cache: Some(nautilus_common::cache::CacheConfig {
                bar_capacity: 1,
                ..Default::default()
            }),
            ..Default::default()
        })
        .raise_exception(true)
        .dispose_on_completion(false)
        .build()
        .unwrap();
    let mut node = BacktestNode::new(vec![config.clone()]).unwrap();
    let outputs = Arc::new(Mutex::new(Vec::new()));
    let sink = outputs.clone();
    let json = r#"{"columns":["CLOSE","HIGH"],"nodes":[{"kind":"column","index":0},{"kind":"column","index":1},
      {"kind":"rolling","child":0,"window":2,"op":"mean","min_periods":1,"propagate_nan":false}],"outputs":[2,1]}"#;
    for fields in [
        vec!["CLOSE"],
        vec!["CLOSE", "OPEN_INTEREST"],
        vec!["HIGH", "CLOSE"],
    ] {
        assert!(
            attach_factor_plan(
                &mut node,
                "native-factor-catalog",
                "invalid-fields",
                json,
                &["factor-product"],
                &[bar_type],
                &fields,
                |_: &nautilus_factor_bridge::FactorUpdate| Ok(())
            )
            .is_err()
        );
        assert!(
            node.get_engines().is_empty(),
            "invalid inputs must fail before native Catalog loading"
        );
    }
    let boundary_json = r#"{"nodes":[{"kind":"column","index":0},{"kind":"boundary","index":0},{"kind":"session_reset","child":0,"boundary":1,"op":"mean","min_periods":1,"propagate_nan":false}],"outputs":[2]}"#;
    let term_json = r#"{"nodes":[{"kind":"column","index":0},{"kind":"term","op":"term_spread","near_rank":0,"far_rank":1,"depth":4}],"outputs":[1]}"#;
    for plan in [boundary_json, term_json] {
        assert!(
            attach_factor_plan(
                &mut node,
                "native-factor-catalog",
                "missing-context",
                plan,
                &["factor-product"],
                &[bar_type],
                &["CLOSE"],
                |_: &nautilus_factor_bridge::FactorUpdate| Ok(())
            )
            .is_err()
        );
        assert!(node.get_engines().is_empty());
    }
    let handle = attach_factor_plan(
        &mut node,
        "native-factor-catalog",
        "catalog-factor",
        json,
        &["factor-product"],
        &[bar_type],
        &["CLOSE", "HIGH"],
        move |update: &nautilus_factor_bridge::FactorUpdate| {
            sink.lock().unwrap().push((
                update.timestamp_ns,
                update.available_at_ns,
                update.values.clone(),
            ));
            Ok(())
        },
    )
    .unwrap();
    let results = node.run().unwrap();
    handle.ensure_success().unwrap();
    assert_eq!(results.len(), 1);
    let values = outputs.lock().unwrap();
    assert_eq!(
        values.len(),
        8,
        "actual DataEngine subscriptions must drive the factor Actor"
    );
    for (index, (timestamp, available, actual)) in values.iter().enumerate() {
        assert_eq!(*timestamp, bars[index].ts_event.as_u64() as i64);
        assert_eq!(*available, bars[index].ts_init.as_u64() as i64);
        assert_eq!(
            actual[0],
            if index == 0 {
                100.0
            } else {
                99.5 + index as f64
            }
        );
        assert_eq!(actual[1], 110.0 + index as f64);
    }
    assert_eq!(
        node.get_engine("native-factor-catalog")
            .unwrap()
            .kernel()
            .cache
            .borrow()
            .bar_count(&bar_type),
        1
    );
    node.dispose();

    struct FailingFinish;
    impl nautilus_factor_bridge::FactorOutputSink for FailingFinish {
        fn write_update(&mut self, _: &nautilus_factor_bridge::FactorUpdate) -> anyhow::Result<()> {
            Ok(())
        }
        fn finish(&mut self) -> anyhow::Result<()> {
            anyhow::bail!("test output flush failed")
        }
    }
    let mut failed = BacktestNode::new(vec![config.clone()]).unwrap();
    let outcome = attach_factor_plan(
        &mut failed,
        "native-factor-catalog",
        "failed-output",
        json,
        &["factor-product"],
        &[bar_type],
        &["CLOSE", "HIGH"],
        FailingFinish,
    )
    .unwrap();
    failed.run().unwrap();
    assert!(
        outcome
            .ensure_success()
            .unwrap_err()
            .to_string()
            .contains("output flush failed")
    );
    failed.dispose();

    let mut failed = BacktestNode::new(vec![config]).unwrap();
    let outcome = attach_factor_plan(
        &mut failed,
        "native-factor-catalog",
        "failed-write",
        json,
        &["factor-product"],
        &[bar_type],
        &["CLOSE", "HIGH"],
        |_: &nautilus_factor_bridge::FactorUpdate| anyhow::bail!("test output write failed"),
    )
    .unwrap();
    failed.run().unwrap();
    assert!(
        outcome
            .ensure_success()
            .unwrap_err()
            .to_string()
            .contains("output write failed")
    );
    failed.dispose();
}
