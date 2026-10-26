//! Attaches factor computation to Nautilus' existing catalog-driven runtime.
//!
//! The caller owns the complete frozen BacktestRunConfig. This bridge neither
//! loads a second market panel nor implements a second replay/merge loop.

use nautilus_backtest::node::BacktestNode;
use std::sync::{Arc, Mutex};

#[must_use = "check the factor outcome after the native node completes"]
pub struct FactorReplayHandle { error: Arc<Mutex<Option<String>>> }

impl FactorReplayHandle {
    pub fn ensure_success(&self) -> anyhow::Result<()> {
        let error = self.error.lock().map_err(|_| anyhow::anyhow!("factor error state poisoned"))?;
        if let Some(error) = error.as_ref() { anyhow::bail!("factor replay failed: {error}"); }
        Ok(())
    }
}
use nautilus_model::data::BarType;

use crate::{FactorUpdate, nautilus::FactorActor};

/// Registers one shared plan before the native node starts its streaming replay.
/// The sink must consume or persist updates without retaining unbounded history.
pub fn attach_factor_plan(
    node: &mut BacktestNode,
    run_id: &str,
    actor_id: &str,
    plan_json: &str,
    products: &[&str],
    bar_types: &[BarType],
    fields: &[&str],
    sink: impl Fn(&FactorUpdate) + Send + 'static,
) -> anyhow::Result<FactorReplayHandle> {
    let config = node.configs().iter().find(|config| config.id() == run_id)
        .ok_or_else(|| anyhow::anyhow!("unknown native run {run_id}"))?;
    anyhow::ensure!(config.chunk_size().is_some(), "factor catalog replay requires native streaming mode");
    anyhow::ensure!(config.raise_exception(), "factor replay must propagate native errors");
    anyhow::ensure!(!products.is_empty(), "factor products must not be empty");
    anyhow::ensure!(products.iter().collect::<std::collections::HashSet<_>>().len() == products.len(),
        "duplicate frozen factor product");
    let mut actor = FactorActor::from_plan_json(actor_id, products.len(), plan_json)?;
    anyhow::ensure!(actor.input_fields() == fields.len(), "factor plan field count differs from frozen Bar inputs");
    actor.expect_products(products);
    actor.configure_bar_inputs(bar_types, fields)?;
    actor.set_update_sink(sink);
    let error = Arc::new(Mutex::new(None));
    let error_sink = error.clone();
    actor.set_error_sink(move |message| {
        let mut error = error_sink.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        if error.is_none() { *error = Some(message.to_owned()); }
    });
    node.build()?;
    node.get_engine_mut(run_id)
        .ok_or_else(|| anyhow::anyhow!("native run {run_id} was not built"))?
        .add_actor(actor)?;
    Ok(FactorReplayHandle { error })
}
