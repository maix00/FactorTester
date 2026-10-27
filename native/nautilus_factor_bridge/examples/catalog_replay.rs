//! Offline acceptance harness, not a replacement RunSpec or a trading Job runner.
//! Nautilus owns all reading, merge, cache and replay; no Python per-Bar calls.
use nautilus_backtest::{
    config::{BacktestDataConfig, BacktestEngineConfig, BacktestRunConfig, BacktestVenueConfig},
    node::BacktestNode,
};
use nautilus_common::cache::CacheConfig;
use nautilus_execution::models::fee::{FeeModelAny, MakerTakerFeeModel};
use nautilus_factor_bridge::{output::JsonFactorSink, replay::attach_factor_plan};
use nautilus_model::{
    data::{BarType, NautilusDataType},
    enums::{AccountType, BookType, OmsType},
};
use serde::Deserialize;
use std::{
    fs::{File, OpenOptions},
    time::Instant,
};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Product {
    product: String,
    catalog_path: String,
    bar_type: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    venue: String,
    starting_balances: Vec<String>,
    products: Vec<Product>,
    fields: Vec<String>,
    plan: serde_json::Value,
    chunk_size: usize,
    cache_bar_capacity: usize,
    expected_slices: u64,
}

fn main() -> anyhow::Result<()> {
    let args: Vec<_> = std::env::args().collect();
    anyhow::ensure!(
        args.len() == 3,
        "usage: catalog_replay manifest.json new-output.jsonl"
    );
    let manifest: Manifest = serde_json::from_reader(File::open(&args[1])?)?;
    anyhow::ensure!(
        manifest.expected_slices > 0,
        "expected output slices must be positive"
    );
    let cache = CacheConfig::builder()
        .bar_capacity(manifest.cache_bar_capacity)
        .build()?;
    let types = manifest
        .products
        .iter()
        .map(|product| product.bar_type.parse::<BarType>())
        .collect::<Result<Vec<_>, _>>()?;
    anyhow::ensure!(
        types
            .iter()
            .all(|bar_type| bar_type.instrument_id().venue.to_string() == manifest.venue),
        "this acceptance harness requires one explicitly declared venue"
    );
    let venue = BacktestVenueConfig::builder()
        .name(ustr::Ustr::from(&manifest.venue))
        .oms_type(OmsType::Netting)
        .account_type(AccountType::Margin)
        .book_type(BookType::L1_MBP)
        .starting_balances(manifest.starting_balances)
        // This harness submits no orders; explicit zero fees are test configuration.
        .fee_model(FeeModelAny::MakerTaker(MakerTakerFeeModel::zero()))
        .build()?;
    let data = manifest
        .products
        .iter()
        .map(|product| {
            BacktestDataConfig::builder()
                .data_type(NautilusDataType::Bar)
                .catalog_path(product.catalog_path.clone())
                .bar_types(vec![product.bar_type.clone()])
                .build()
        })
        .collect::<Result<Vec<_>, _>>()?;
    let config = BacktestRunConfig::builder()
        .id("catalog-factor-acceptance".to_owned())
        .venues(vec![venue])
        .data(data)
        .chunk_size(manifest.chunk_size)
        .engine(BacktestEngineConfig {
            bypass_logging: true,
            run_analysis: false,
            cache: Some(cache),
            ..Default::default()
        })
        .raise_exception(true)
        .dispose_on_completion(false)
        .build()?;
    let mut node = BacktestNode::new(vec![config])?;
    let output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&args[2])?;
    let products = manifest
        .products
        .iter()
        .map(|product| product.product.as_str())
        .collect::<Vec<_>>();
    let fields = manifest
        .fields
        .iter()
        .map(String::as_str)
        .collect::<Vec<_>>();
    let started = Instant::now();
    let outcome = attach_factor_plan(
        &mut node,
        "catalog-factor-acceptance",
        "factor-plan",
        &manifest.plan.to_string(),
        &products,
        &types,
        &fields,
        JsonFactorSink::new(output, Some(manifest.expected_slices)),
    )?;
    let result = node.run()?;
    outcome.ensure_success()?;
    let elapsed = started.elapsed().as_secs_f64();
    anyhow::ensure!(result.len() == 1, "native replay produced no completed run");
    println!(
        "RESULT_JSON {}",
        serde_json::json!({"input_bars":result[0].iterations,"factor_slices":manifest.expected_slices,
        "elapsed_s":elapsed,"per_bar_python_calls":0,"cache_bar_capacity":manifest.cache_bar_capacity,"chunk_size":manifest.chunk_size})
    );
    node.dispose();
    Ok(())
}
