//! Factor execution bridge.
//!
//! Nautilus core does not depend on this crate.  A Nautilus actor/plugin
//! depends on the bridge (or the bridge depends on the optional Nautilus
//! feature), keeping py-alpha-lib independent.

use alpha_algo::{IntervalKernel, SessionOp};

pub mod plan;
#[cfg(feature = "nautilus-backtest")]
pub mod replay;
#[cfg(feature = "nautilus")]
pub mod boundary;
pub use plan::{BinaryOp, CrossOp, ExprSpec, FactorPlanEngine};

#[derive(Clone, Debug)]
pub struct MarketBar {
    pub timestamp_ns: i64,
    /// Actual availability of this completed slice, distinct from its Bar clock.
    pub available_at_ns: i64,
    pub products: Vec<String>,
    pub values: Vec<f64>,
    pub term_curves: Vec<Vec<(f64, f64)>>,
    /// Channel-major flags for this slice only; the plan manifest fixes order.
    pub boundaries: Vec<u8>,
}

impl MarketBar {
    pub fn with_boundaries(mut self, boundaries: Vec<u8>) -> Self {
        self.boundaries = boundaries;
        self
    }
    pub fn with_term_curves(mut self, curves: Vec<Vec<(f64, f64)>>) -> Self {
        self.term_curves = curves;
        self
    }

    pub fn new(timestamp_ns: i64, products: Vec<String>, values: Vec<f64>) -> Self {
        Self { timestamp_ns, available_at_ns: timestamp_ns, products, values, term_curves: Vec::new(), boundaries: Vec::new() }
    }
}

#[derive(Clone, Debug)]
pub struct FactorUpdate {
    pub timestamp_ns: i64,
    pub available_at_ns: i64,
    pub products: Vec<String>,
    pub values: Vec<f64>,
}

/// Bounded output consumer; finish is called when Nautilus stops the Actor.
pub trait FactorOutputSink: Send {
    fn write_update(&mut self, update: &FactorUpdate) -> anyhow::Result<()>;
    fn finish(&mut self) -> anyhow::Result<()> { Ok(()) }
}

impl<F: FnMut(&FactorUpdate) -> anyhow::Result<()> + Send> FactorOutputSink for F {
    fn write_update(&mut self, update: &FactorUpdate) -> anyhow::Result<()> { self(update) }
}

pub trait FactorEngine {
    type Error;
    fn warmup(&mut self) -> Result<(), Self::Error> { Ok(()) }
    fn update(&mut self, bar: &MarketBar) -> Result<Vec<f64>, Self::Error>;
    fn update_into(&mut self, bar: &MarketBar, output: &mut Vec<f64>) -> Result<(), Self::Error> {
        let values = self.update(bar)?;
        output.clear();
        output.extend(values);
        Ok(())
    }
}

/// Minimal single-window engine proving the bridge owns Rust factor state.
pub struct WindowEngine {
    window: usize,
    state: IntervalKernel,
    ordinal: u64,
}

impl WindowEngine {
    pub fn new(window: usize, op: SessionOp) -> Result<Self, alpha_algo::Error> {
        if window == 0 {
            return Err(alpha_algo::Error::InvalidParameter("window must be positive".into()));
        }
        Ok(Self {
            window,
            state: IntervalKernel::new_explicit(op)?,
            ordinal: 0,
        })
    }
}

impl FactorEngine for WindowEngine {
    type Error = alpha_algo::Error;

    fn update(&mut self, bar: &MarketBar) -> Result<Vec<f64>, Self::Error> {
        let current = self.ordinal;
        let start = current.saturating_sub(self.window as u64 - 1);
        let value = bar.values.first().copied().unwrap_or(f64::NAN);
        self.ordinal += 1;
        Ok(vec![self.state.update_explicit(start, current, value)])
    }
}


/// Several factor windows updated from one market bar.  Each engine owns its
/// own Rust interval state; shared inputs are read once.
pub struct MultiWindowEngine {
    pub names: Vec<String>,
    engines: Vec<WindowEngine>,
}

impl MultiWindowEngine {
    pub fn new(specs: Vec<(String, usize, SessionOp)>) -> Result<Self, alpha_algo::Error> {
        let n = specs.len();
        let names: Vec<String> = specs.iter().map(|(name, _, _)| name.clone()).collect();
        let engines = specs.into_iter().map(|(_, window, op)| WindowEngine::new(window, op)).collect::<Result<Vec<_>, _>>()?;
        debug_assert_eq!(names.len(), n);
        Ok(Self { names, engines })
    }
}

impl FactorEngine for MultiWindowEngine {
    type Error = alpha_algo::Error;

    fn update(&mut self, bar: &MarketBar) -> Result<Vec<f64>, Self::Error> {
        Ok(self.engines.iter_mut().map(|engine| engine.update(bar).map(|values| values[0])).collect::<Result<Vec<_>, _>>()?)
    }
}

/// One window across every product in a `MarketBar`.
pub struct ProductWindowEngine {
    window: usize,
    states: Vec<IntervalKernel>,
    ordinal: u64,
}

impl ProductWindowEngine {
    pub fn new(products: usize, window: usize, op: SessionOp) -> Result<Self, alpha_algo::Error> {
        if products == 0 || window == 0 {
            return Err(alpha_algo::Error::InvalidParameter("products/window must be positive".into()));
        }
        let states = (0..products).map(|_| IntervalKernel::new_explicit(op)).collect::<Result<Vec<_>, _>>()?;
        Ok(Self { window, states, ordinal: 0 })
    }
}

impl FactorEngine for ProductWindowEngine {
    type Error = alpha_algo::Error;

    fn update(&mut self, bar: &MarketBar) -> Result<Vec<f64>, Self::Error> {
        if bar.values.len() != self.states.len() {
            return Err(alpha_algo::Error::InvalidParameter("market bar product width mismatch".into()));
        }
        let current = self.ordinal;
        let start = current.saturating_sub(self.window as u64 - 1);
        self.ordinal += 1;
        Ok(self.states.iter_mut().zip(bar.values.iter()).map(|(state, value)| state.update_explicit(start, current, *value)).collect())
    }
}

/// Matrix of independent window factors: factors x products.
pub struct MatrixPlanEngine {
    states: Vec<Vec<IntervalKernel>>,
    windows: Vec<usize>,
    products: usize,
    ordinal: u64,
}

impl MatrixPlanEngine {
    pub fn new(products: usize, specs: &[(usize, SessionOp)]) -> Result<Self, alpha_algo::Error> {
        if products == 0 || specs.is_empty() {
            return Err(alpha_algo::Error::InvalidParameter("matrix plan requires factors and products".into()));
        }
        let mut states = Vec::with_capacity(specs.len());
        let mut windows = Vec::with_capacity(specs.len());
        for (window, op) in specs {
            windows.push(*window);
            states.push((0..products).map(|_| IntervalKernel::new_explicit(*op)).collect::<Result<Vec<_>, _>>()?);
        }
        Ok(Self { states, windows, products, ordinal: 0 })
    }
}

impl FactorEngine for MatrixPlanEngine {
    type Error = alpha_algo::Error;

    fn update(&mut self, bar: &MarketBar) -> Result<Vec<f64>, Self::Error> {
        if bar.values.len() != self.products {
            return Err(alpha_algo::Error::InvalidParameter("matrix plan product width mismatch".into()));
        }
        let current = self.ordinal;
        self.ordinal += 1;
        let mut out = Vec::with_capacity(self.states.len() * self.products);
        for (states, window) in self.states.iter_mut().zip(&self.windows) {
            let start = current.saturating_sub(*window as u64 - 1);
            for (state, value) in states.iter_mut().zip(&bar.values) {
                out.push(state.update_explicit(start, current, *value));
            }
        }
        Ok(out)
    }
}

/// Product-parallel plan for non-cross-sectional factors.  A cross-sectional
/// node is not allowed here; use `FactorPlanEngine` for that barrier case.
pub struct ProductParallelPlanEngine {
    lanes: Vec<plan::FactorPlanEngine>,
    outputs: usize,
}

impl ProductParallelPlanEngine {
    /// Evaluate a whole batch with one independent lane per product.
    pub fn update_batch(&mut self, bars: &[MarketBar]) -> Result<Vec<Vec<f64>>, alpha_algo::Error> {
        use rayon::prelude::*;
        let per_product: Vec<Vec<Vec<f64>>> = self.lanes
            .par_iter_mut()
            .enumerate()
            .map(|(product, lane)| bars.iter().map(|bar| {
                let value = *bar.values.get(product).ok_or_else(|| {
                    alpha_algo::Error::InvalidParameter("parallel batch product width mismatch".into())
                })?;
                lane.update(&MarketBar::new(bar.timestamp_ns, Vec::new(), vec![value]))
            }).collect())
            .collect::<Result<Vec<_>, _>>()?;
        let mut out = Vec::with_capacity(bars.len());
        for index in 0..bars.len() {
            let mut row = Vec::with_capacity(self.outputs * per_product.len());
            for factor in 0..self.outputs {
                for product in &per_product { row.push(product[index][factor]); }
            }
            out.push(row);
        }
        Ok(out)
    }

    pub fn new(products: usize, specs: Vec<plan::ExprSpec>, outputs: Vec<usize>) -> Result<Self, alpha_algo::Error> {
        use rayon::prelude::*;
        if specs.iter().any(|spec| matches!(spec, plan::ExprSpec::Cross { .. })) {
            return Err(alpha_algo::Error::InvalidParameter("use FactorPlanEngine for cross-sectional nodes".into()));
        }
        let lanes = (0..products)
            .into_par_iter()
            .map(|_| plan::FactorPlanEngine::new(1, specs.clone(), outputs.clone()))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(Self { outputs: outputs.len(), lanes })
    }
}

impl FactorEngine for ProductParallelPlanEngine {
    type Error = alpha_algo::Error;

    fn update(&mut self, bar: &MarketBar) -> Result<Vec<f64>, Self::Error> {
        use rayon::prelude::*;
        if bar.values.len() != self.lanes.len() {
            return Err(alpha_algo::Error::InvalidParameter("parallel plan product width mismatch".into()));
        }
        let per_product: Vec<Vec<f64>> = self.lanes
            .par_iter_mut()
            .zip(bar.values.par_iter())
            .map(|(lane, value)| lane.update(&MarketBar::new(bar.timestamp_ns, Vec::new(), vec![*value])))
            .collect::<Result<Vec<_>, _>>()?;
        let mut out = Vec::with_capacity(self.outputs * per_product.len());
        for factor in 0..self.outputs {
            for lane in &per_product {
                out.push(lane[factor]);
            }
        }
        Ok(out)
    }
}

/// Nautilus-side adapter contract.  Implemented by the actor that receives
/// Nautilus bars; it does not leak Nautilus types into py-alpha-lib.
pub trait NautilusMarketAdapter {
    fn timestamp_ns(&self) -> i64;
    fn products(&self) -> &[String];
    fn values(&self) -> &[f64];

    fn to_market_bar(&self) -> MarketBar {
        MarketBar::new(self.timestamp_ns(), self.products().to_vec(), self.values().to_vec())
    }
}

#[cfg(feature = "nautilus")]
pub mod nautilus {
    //! Concrete Nautilus adapters.  Kept behind a feature so Nautilus core
    //! never depends on this crate.
    pub use nautilus_core as core;

    use std::fmt;

    use nautilus_common::actor::{DataActor, DataActorConfig, DataActorCore, DataActorNative};
    use nautilus_model::data::{Bar, BarType};
    use nautilus_model::identifiers::{ActorId, InstrumentId, Symbol};
    use ustr::Ustr;

    use crate::{FactorEngine, FactorUpdate, FactorOutputSink, MarketBar};

    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    enum BarField { Open, High, Low, Close, Volume }

    impl BarField {
        fn parse(name: &str) -> anyhow::Result<Self> {
            match name {
                "O" | "OPEN" | "OPEN_ADJUSTED" => Ok(Self::Open),
                "H" | "HIGH" | "HIGH_ADJUSTED" => Ok(Self::High),
                "L" | "LOW" | "LOW_ADJUSTED" => Ok(Self::Low),
                "C" | "CLOSE" | "CLOSE_ADJUSTED" => Ok(Self::Close),
                "V" | "VOLUME" => Ok(Self::Volume),
                _ => anyhow::bail!("field {name} is not supplied by Nautilus Bar; an authoritative custom event is required"),
            }
        }

        fn value(self, bar: &Bar) -> f64 {
            match self {
                Self::Open => bar.open.as_f64(), Self::High => bar.high.as_f64(),
                Self::Low => bar.low.as_f64(), Self::Close => bar.close.as_f64(),
                Self::Volume => bar.volume.as_f64(),
            }
        }
    }

    /// Minimal Nautilus actor that owns the Rust factor engine and consumes
    /// `Bar` messages.  Registration with a trader is the caller's job.
    pub struct FactorActor<E> {
        id: Ustr,
        engine: E,
        last_error: Option<String>,
        expected_products: Vec<String>,
        symbol_index: std::collections::HashMap<Symbol, usize>,
        id_index: std::collections::HashMap<InstrumentId, usize>,
        bar_types: Vec<BarType>,
        fields: Vec<BarField>,
        pending_bars: Vec<Option<Bar>>,
        pending_count: usize,
        pending_available_at_ns: i64,
        market: MarketBar,
        last_update: Option<FactorUpdate>,
        boundary_buffer: Vec<u8>,
        pending_boundaries: std::collections::BTreeMap<i64, Vec<u8>>,
        pending_timestamp: Option<i64>,
        future_slices: std::collections::BTreeMap<i64, std::collections::BTreeMap<usize, Bar>>,
        max_future_slices: usize,
        barrier_grace_ns: Option<i64>,
        sink: Option<Box<dyn FactorOutputSink>>,
        error_sink: Option<Box<dyn Fn(&str) + Send>>,
        core: DataActorCore,
    }

    impl<E> fmt::Debug for FactorActor<E> {
        fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            f.debug_struct("FactorActor").field("id", &self.id).finish()
        }
    }

    impl<E: FactorEngine + 'static> FactorActor<E>
    where E::Error: std::fmt::Display,
{
        pub fn new(actor_id: &str, engine: E) -> Self {
            let core = DataActorCore::new(DataActorConfig {
                actor_id: Some(ActorId::new(actor_id)), ..Default::default()
            });
            Self {
                id: Ustr::from(actor_id), engine, last_error: None,
                core,
                expected_products: Vec::new(),
                symbol_index: std::collections::HashMap::new(),
                id_index: std::collections::HashMap::new(),
                bar_types: Vec::new(),
                fields: vec![BarField::Close],
                pending_bars: Vec::new(),
                pending_count: 0,
                pending_available_at_ns: 0,
                market: MarketBar::new(0, Vec::new(), Vec::new()),
                pending_timestamp: None,
                future_slices: std::collections::BTreeMap::new(),
                max_future_slices: 64,
                barrier_grace_ns: None,
                sink: None,
                error_sink: None,
                last_update: None,
                boundary_buffer: Vec::new(),
                pending_boundaries: std::collections::BTreeMap::new(),
            }
        }

        pub fn latest(&self) -> &[f64] { self.last_update.as_ref().map_or(&[], |update| update.values.as_slice()) }

        pub fn last_error(&self) -> Option<&str> { self.last_error.as_deref() }

        /// Queue an authoritative boundary before its completed slice. Bound
        /// queued events with the same budget as out-of-order market slices.
        pub fn queue_boundary(&mut self, timestamp_ns: i64, flags: &[u8]) -> anyhow::Result<()> {
            if flags.len() != self.boundary_buffer.len() || flags.is_empty() {
                anyhow::bail!("boundary shape differs from frozen plan");
            }
            if self.last_update.as_ref().is_some_and(|update| timestamp_ns <= update.timestamp_ns) {
                anyhow::bail!("boundary arrived after its slice was executed");
            }
            if !self.pending_boundaries.contains_key(&timestamp_ns) && self.pending_boundaries.len() >= self.max_future_slices {
                anyhow::bail!("boundary queue capacity exceeded");
            }
            let queued = self.pending_boundaries.entry(timestamp_ns).or_insert_with(|| vec![0; flags.len()]);
            for (value, &flag) in queued.iter_mut().zip(flags) { *value |= u8::from(flag != 0); }
            Ok(())
        }

        fn evaluate_market_ref(&mut self, market: &mut MarketBar) -> anyhow::Result<()> {
            if self.last_update.as_ref().is_some_and(|update| market.timestamp_ns <= update.timestamp_ns) {
                anyhow::bail!("market slice must follow the last completed slice");
            }
            if let Some(flags) = self.pending_boundaries.remove(&market.timestamp_ns) {
                self.boundary_buffer.copy_from_slice(&flags);
            }
            // Move the reusable buffer into the temporary input and back;
            // there is no per-Bar boundary allocation or copy.
            std::mem::swap(&mut market.boundaries, &mut self.boundary_buffer);
            let had_update = self.last_update.is_some();
            let mut update = self.last_update.take().unwrap_or_else(|| FactorUpdate {
                timestamp_ns: market.timestamp_ns, available_at_ns: market.available_at_ns, products: Vec::new(), values: Vec::new(),
            });
            let result = self.engine.update_into(market, &mut update.values);
            std::mem::swap(&mut market.boundaries, &mut self.boundary_buffer);
            self.boundary_buffer.fill(0);
            match result {
                Ok(()) => {
                    update.timestamp_ns = market.timestamp_ns;
                    update.available_at_ns = market.available_at_ns;
                    if !had_update || (self.expected_products.is_empty() && update.products != market.products) {
                        update.products.clone_from(&market.products);
                    }
                    self.last_update = Some(update);
                    self.last_error = None;
                    if let Err(error) = self.publish() {
                        self.last_error = Some(error.to_string());
                        return Err(error);
                    }
                    Ok(())
                }
                Err(error) => {
                    if had_update { self.last_update = Some(update); }
                    self.last_error = Some(error.to_string());
                    Err(anyhow::anyhow!(error.to_string()))
                }
            }
        }

        fn evaluate_market(&mut self, mut market: MarketBar) -> anyhow::Result<()> {
            self.evaluate_market_ref(&mut market)
        }

        pub fn set_max_future_slices(&mut self, limit: usize) { self.max_future_slices = limit.max(1); }

        pub fn set_barrier_grace(&mut self, grace_ns: i64) { self.barrier_grace_ns = Some(grace_ns.max(0)); }

        pub fn on_timer(&mut self, now_ns: i64) -> usize {
            match self.barrier_grace_ns {
                Some(grace) => self.expire_stale(now_ns, grace),
                None => 0,
            }
        }

        pub fn set_update_sink(&mut self, mut sink: impl FnMut(&FactorUpdate) + Send + 'static) {
            self.set_output_sink(move |update: &FactorUpdate| { sink(update); Ok(()) });
        }

        pub fn set_output_sink(&mut self, sink: impl FactorOutputSink + 'static) {
            self.sink = Some(Box::new(sink));
        }

        pub fn set_error_sink(&mut self, sink: impl Fn(&str) + Send + 'static) {
            self.error_sink = Some(Box::new(sink));
        }

        fn report_runtime_error(&self, error: &str) {
            if let Some(sink) = self.error_sink.as_ref() {
                sink(error);
                self.shutdown_system(Some(error.to_owned()));
            }
        }

        fn publish(&mut self) -> anyhow::Result<()> {
            if let (Some(sink), Some(update)) = (self.sink.as_mut(), self.last_update.as_ref()) {
                sink.write_update(update)?;
            }
            Ok(())
        }

        /// Drop slices older than ``now_ns - grace_ns``; report dropped work.
        pub fn expire_stale(&mut self, now_ns: i64, grace_ns: i64) -> usize {
            let cutoff = now_ns.saturating_sub(grace_ns);
            let before = self.pending_len();
            self.future_slices = self.future_slices.split_off(&cutoff);
            self.pending_boundaries = self.pending_boundaries.split_off(&cutoff);
            if self.pending_timestamp.is_some_and(|timestamp| timestamp < cutoff) {
                self.pending_bars.fill(None);
                self.pending_count = 0;
            self.pending_available_at_ns = 0;
                self.pending_timestamp = None;
            }
            let dropped = before - self.pending_len();
            if dropped > 0 {
                self.last_error = Some(format!("dropped {dropped} stale slice bars"));
            }
            dropped
        }

        pub fn expire_before(&mut self, timestamp_ns: i64) {
            self.future_slices = self.future_slices.split_off(&timestamp_ns);
            self.pending_boundaries = self.pending_boundaries.split_off(&timestamp_ns);
            if self.pending_timestamp.is_some_and(|timestamp| timestamp < timestamp_ns) {
                self.pending_bars.fill(None);
                self.pending_count = 0;
            self.pending_available_at_ns = 0;
                self.pending_timestamp = None;
            }
        }

        pub fn pending_len(&self) -> usize {
            self.pending_count
                + self.future_slices.values().map(|slice| slice.len()).sum::<usize>()
        }

        pub fn last_update(&self) -> Option<&FactorUpdate> { self.last_update.as_ref() }

        /// Publish the latest update through Nautilus' runtime-typed message bus.
        pub fn publish_last_update(&self, topic: &str) {
            use nautilus_common::msgbus::mstr::{MStr, Topic};
            if let Some(update) = self.last_update.as_ref() {
                nautilus_common::msgbus::publish_any(MStr::<Topic>::from(topic), update);
            }
        }

        pub fn expect_products(&mut self, products: &[&str]) {
            self.expected_products = products.iter().map(|product| product.to_string()).collect();

            self.symbol_index = self.expected_products.iter().enumerate()
                .map(|(index, product)| (Symbol::new(product), index)).collect();
            self.id_index = self.expected_products.iter().enumerate()
                .filter_map(|(index, product)| product.parse::<InstrumentId>().ok().map(|id| (id, index)))
                .collect();
            self.pending_bars = vec![None; self.expected_products.len()];
            self.pending_count = 0;
            self.pending_available_at_ns = 0;
            self.market.products.clone_from(&self.expected_products);
            self.market.values.clear();
            self.market.values.reserve(self.expected_products.len());
            self.pending_timestamp = None;
        }

        /// Freezes one base-clock Bar stream per product, in the plan's product order.
        pub fn configure_bar_inputs(&mut self, bar_types: &[BarType], fields: &[&str]) -> anyhow::Result<()> {
            anyhow::ensure!(!self.expected_products.is_empty() && bar_types.len() == self.expected_products.len(),
                "one Bar type is required for each frozen product");
            anyhow::ensure!(self.pending_timestamp.is_none() && self.last_update.is_none(), "Bar inputs must be frozen before replay");
            let fields = fields.iter().map(|name| BarField::parse(name)).collect::<anyhow::Result<Vec<_>>>()?;
            let ids: std::collections::HashMap<_,_> = bar_types.iter().enumerate()
                .map(|(index, bar_type)| (bar_type.instrument_id(), index)).collect();
            anyhow::ensure!(ids.len() == bar_types.len(), "duplicate instrument in frozen Bar inputs");
            anyhow::ensure!(bar_types.iter().all(|bar_type| bar_type.spec() == bar_types[0].spec()),
                "one shared factor Actor requires one base Bar specification");
            self.id_index = ids;
            self.symbol_index.clear();
            self.bar_types = bar_types.to_vec();
            self.fields = fields;
            self.market.values.reserve(self.fields.len() * self.expected_products.len());
            Ok(())
        }

        /// Collect one Bar per frozen product before updating the shared plan.
        pub fn on_completed_bar(&mut self, bar: &Bar) {
            if self.expected_products.is_empty() {
                let _ = self.on_bar(bar);
                return;
            }
            let instrument_id = bar.bar_type.instrument_id();
            let index = self.id_index.get(&instrument_id).copied()
                .or_else(|| self.symbol_index.get(&instrument_id.symbol).copied());
            let Some(index) = index else {
                self.last_error = Some(format!("unexpected product {instrument_id}"));
                return;
            };

            let timestamp = bar.ts_event.as_u64() as i64;
            if let Some(pending) = self.pending_timestamp {
                if timestamp < pending {
                    self.last_error = Some(format!("out-of-order slice {timestamp} after {pending}"));
                    return;
                }
                if timestamp > pending {
                    if !self.future_slices.contains_key(&timestamp) && self.future_slices.len() >= self.max_future_slices {
                        self.last_error = Some(format!("future slice limit {} exceeded", self.max_future_slices));
                        return;
                    }
                    self.future_slices.entry(timestamp).or_default().insert(index, bar.clone());
                    return;
                }
            } else {
                self.pending_timestamp = Some(timestamp);
            }
            if self.pending_bars[index].is_none() { self.pending_count += 1; }
            self.pending_available_at_ns = self.pending_available_at_ns.max(bar.ts_init.as_u64() as i64);
            self.pending_bars[index] = Some(bar.clone());
            if self.pending_count == self.expected_products.len() {
                self.flush_slice();
            }
        }

        fn flush_slice(&mut self) {
            let Some(timestamp) = self.pending_timestamp else { return };
            if self.pending_count != self.expected_products.len() { return; }
            self.market.timestamp_ns = timestamp;
            self.market.available_at_ns = self.pending_available_at_ns;
            self.market.values.clear();
            for slot in &self.pending_bars {
                let bar = slot.as_ref().expect("completed slice slot");
                for field in &self.fields { self.market.values.push(field.value(bar)); }
            }
            self.pending_bars.fill(None);
            self.pending_count = 0;
            self.pending_available_at_ns = 0;
            let mut market = std::mem::replace(&mut self.market, MarketBar::new(0, Vec::new(), Vec::new()));
            let _ = self.evaluate_market_ref(&mut market);
            self.market = market;
            self.pending_timestamp = None;
            while let Some((&next, slice)) = self.future_slices.iter().next() {
                if slice.len() != self.expected_products.len() { break; }
                let slice = self.future_slices.remove(&next).unwrap();
                self.pending_count = slice.len();
                for (index, bar) in slice {
                    self.pending_available_at_ns = self.pending_available_at_ns.max(bar.ts_init.as_u64() as i64);
                    self.pending_bars[index] = Some(bar);
                }
                self.pending_timestamp = Some(next);
                self.flush_slice();
            }
        }

        /// Assemble one completed cross-sectional slice and update once.
        pub fn handle_bars(&mut self, bars: &[Bar]) {
            let Some(first) = bars.first() else { return };
            if bars.iter().any(|bar| bar.ts_event != first.ts_event) {
                self.last_error = Some("completed slice has mixed timestamps".into());
                return;
            }
            if !self.expected_products.is_empty() {
                for bar in bars { self.on_completed_bar(bar); }
                return;
            }
            let bar = crate::nautilus::market_bar_from_bars(first.ts_event.as_u64() as i64, bars);
            let _ = self.evaluate_market(bar);
        }

        /// Register this actor in Nautilus' thread-local actor registry.
        pub fn register(self) -> std::rc::Rc<std::cell::UnsafeCell<Self>> {
            nautilus_common::actor::registry::register_actor(self)
        }
    }

    impl<E: FactorEngine + 'static> DataActor for FactorActor<E>
    where E::Error: std::fmt::Display {
        fn on_start(&mut self) -> anyhow::Result<()> {
            for bar_type in self.bar_types.clone() { self.subscribe_bars(bar_type, None, None); }
            if !self.boundary_buffer.is_empty() {
                use nautilus_model::data::{DataType, ensure_custom_data_json_registered};
                ensure_custom_data_json_registered::<crate::boundary::FactorBoundary>()?;
                self.subscribe_data(DataType::new("FactorBoundary", None, None), None, None);
            }
            Ok(())
        }

        fn on_stop(&mut self) -> anyhow::Result<()> {
            let pending = self.pending_len();
            if self.last_update.is_none() && self.error_sink.is_some() {
                let message = "native replay produced no factor updates";
                self.report_runtime_error(message);
                anyhow::bail!(message);
            }
            if let Some(sink) = self.sink.as_mut() {
                if let Err(error) = sink.finish() {
                    self.report_runtime_error(&error.to_string());
                    return Err(error);
                }
            }
            if pending != 0 {
                let message = format!("native replay ended with {pending} incomplete factor input Bars");
                self.report_runtime_error(&message);
                anyhow::bail!(message);
            }
            Ok(())
        }

        fn on_data(&mut self, data: &nautilus_model::data::CustomData) -> anyhow::Result<()> {
            if let Some(boundary) = data.data.as_any().downcast_ref::<crate::boundary::FactorBoundary>() {
                let timestamp = i64::try_from(boundary.timestamp_ns)?;
                if let Err(error) = self.queue_boundary(timestamp, &boundary.flags) {
                    self.report_runtime_error(&error.to_string());
                    return Err(error);
                }
            }
            Ok(())
        }

        fn on_bar(&mut self, bar: &Bar) -> anyhow::Result<()> {
            let result = if self.expected_products.is_empty() {
                self.evaluate_market(MarketBar::from(bar))
            } else {
                self.on_completed_bar(bar);
                match self.last_error.as_ref() {
                    Some(error) => Err(anyhow::anyhow!(error.clone())), None => Ok(()),
                }
            };
            if let Err(error) = &result { self.report_runtime_error(&error.to_string()); }
            result
        }
    }

    impl FactorActor<crate::plan::FactorPlanEngine> {
        pub fn validate_bar_columns(&self, fields: &[&str]) -> anyhow::Result<()> {
            let expected = self.engine.input_columns();
            if !expected.is_empty() {
                let requested = fields.iter().map(|name| BarField::parse(name)).collect::<anyhow::Result<Vec<_>>>()?;
                let frozen = expected.iter().map(|name| BarField::parse(name)).collect::<anyhow::Result<Vec<_>>>()?;
                anyhow::ensure!(requested == frozen, "Bar field mapping differs from frozen factor column order");
            }
            Ok(())
        }

        pub fn input_fields(&self) -> usize { self.engine.input_fields() }
        pub fn boundary_channels(&self) -> usize { self.engine.boundary_channels() }
        pub fn curve_channels(&self) -> usize { self.engine.curve_channels() }

        /// Build an actor directly from the public `alpha.factor` plan JSON.
        pub fn from_plan_json(actor_id: &str, products: usize, json: &str) -> Result<Self, alpha_algo::Error> {
            let engine = crate::plan::FactorPlanEngine::from_spec_json(json, products)?;
            let channels = engine.boundary_channels();
            let mut actor = Self::new(actor_id, engine);
            actor.boundary_buffer = vec![0; channels * products];
            Ok(actor)
        }
    }

    /// Assemble a cross-sectional bar from one Nautilus `Bar` per product.
    pub fn market_bar_from_bars(timestamp_ns: i64, bars: &[Bar]) -> MarketBar {
        let products = bars.iter().map(|bar| bar.bar_type.instrument_id().to_string()).collect();
        let values = bars.iter().map(|bar| bar.close.as_f64()).collect();
        let mut market = MarketBar::new(timestamp_ns, products, values);
        market.available_at_ns = bars.iter().map(|bar| bar.ts_init.as_u64() as i64).max().unwrap_or(timestamp_ns);
        market
    }

    impl<E: FactorEngine + 'static> DataActorNative for FactorActor<E> {
        fn core(&self) -> &DataActorCore { &self.core }
        fn core_mut(&mut self) -> &mut DataActorCore { &mut self.core }
    }

    impl From<&Bar> for MarketBar {
        fn from(bar: &Bar) -> Self {
            Self {
                timestamp_ns: bar.ts_event.as_u64() as i64,
                available_at_ns: bar.ts_init.as_u64() as i64,
                products: vec![bar.bar_type.instrument_id().to_string()],
                values: vec![bar.close.as_f64()],
                term_curves: Vec::new(),
                boundaries: Vec::new(),
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn signal_gap_does_not_make_outer_where_see_a_future_source_value() {
        let json = r#"{"nodes":[{"kind":"column","index":0},
          {"kind":"signal","child":0,"signal_ns":5},
          {"kind":"const","value":100},
          {"kind":"binary","op":"gt","left":1,"right":2},
          {"kind":"const","value":1},{"kind":"const","value":0},
          {"kind":"where","condition":3,"when_true":4,"when_false":5}],"outputs":[1,6]}"#;
        let times = [1,4,11,12,15,16];
        let values = [10.0,40.0,110.0,120.0,150.0,160.0];
        let expected = [f64::NAN,f64::NAN,40.0,40.0,150.0,150.0];
        for prefix in 1..=times.len() {
            let mut engine = FactorPlanEngine::from_spec_json(json,1).unwrap();
            let mut output = Vec::new();
            for row in 0..prefix {
                engine.update_into(&MarketBar::new(times[row],vec!["A".into()],vec![values[row]]),&mut output).unwrap();
                assert!(output[0].is_nan() && expected[row].is_nan() || output[0] == expected[row]);
                assert_eq!(output[1],if expected[row] > 100.0 {1.0} else {0.0});
            }
        }
    }

    #[test]
    fn product_parallel_plan_updates_products_independently() {
        let specs = vec![
            plan::ExprSpec::Column(0),
            plan::ExprSpec::Rolling { child: 0, window: 2, op: SessionOp::Mean, min_periods: 1, propagate_nan: true, trunc_start: -1, trunc_end: -1, trunc_start_child: None, trunc_end_child: None },
        ];
        let mut engine = ProductParallelPlanEngine::new(2, specs, vec![1]).unwrap();
        let bar = MarketBar::new(0, vec!["A".into(), "B".into()], vec![1.0, 10.0]);
        assert_eq!(engine.update(&bar).unwrap(), vec![1.0, 10.0]);
        let bar = MarketBar::new(1, vec!["A".into(), "B".into()], vec![3.0, 30.0]);
        assert_eq!(engine.update(&bar).unwrap(), vec![2.0, 20.0]);
    }

    #[test]
    fn signal_plan_resets_on_calendar_session_boundary() {
        let json = r#"{"columns":["CLOSE"],"nodes":[{"kind":"column","index":0},{"kind":"signal","child":0,"signal_ns":200,"sessions":[[0,200,0],[1000,1200,1000]]}],"outputs":[1]}"#;
        let mut engine = FactorPlanEngine::from_spec_json(json, 1).unwrap();
        let bar = |timestamp, value| MarketBar::new(timestamp, vec!["A".into()], vec![value]);
        assert_eq!(engine.update(&bar(0, 0.0)).unwrap(), vec![0.0]);
        assert_eq!(engine.update(&bar(100, 1.0)).unwrap(), vec![0.0]);
        assert_eq!(engine.update(&bar(200, 2.0)).unwrap(), vec![2.0]);
        // A new calendar session restarts the signal grid at its session start.
        assert_eq!(engine.update(&bar(1000, 10.0)).unwrap(), vec![10.0]);
    }

    #[test]
    fn matrix_plan_engine_updates_factor_product_matrix() {
        let mut engine = MatrixPlanEngine::new(2, &[(2, SessionOp::Mean), (2, SessionOp::Sum)]).unwrap();
        let bar = MarketBar::new(0, vec!["A".into(), "B".into()], vec![2.0, 4.0]);
        assert_eq!(engine.update(&bar).unwrap(), vec![2.0, 4.0, 2.0, 4.0]);
        let bar = MarketBar::new(1, vec!["A".into(), "B".into()], vec![4.0, 8.0]);
        assert_eq!(engine.update(&bar).unwrap(), vec![3.0, 6.0, 6.0, 12.0]);
    }

    #[test]
    fn product_window_engine_updates_every_product() {
        let mut engine = ProductWindowEngine::new(2, 2, SessionOp::Mean).unwrap();
        let bar = MarketBar::new(0, vec!["A".into(), "B".into()], vec![2.0, 4.0]);
        assert_eq!(engine.update(&bar).unwrap(), vec![2.0, 4.0]);
        let bar = MarketBar::new(1, vec!["A".into(), "B".into()], vec![4.0, 8.0]);
        assert_eq!(engine.update(&bar).unwrap(), vec![3.0, 6.0]);
    }

    #[test]
    fn multi_window_engine_updates_shared_bar_once() {
        let mut engine = MultiWindowEngine::new(vec![
            ("mean2".into(), 2, SessionOp::Mean),
            ("sum3".into(), 3, SessionOp::Sum),
        ]).unwrap();
        let bar = |value| MarketBar::new(0, vec!["A".into()], vec![value]);
        assert_eq!(engine.update(&bar(1.0)).unwrap(), vec![1.0, 1.0]);
        assert_eq!(engine.update(&bar(2.0)).unwrap(), vec![1.5, 3.0]);
        assert_eq!(engine.update(&bar(3.0)).unwrap(), vec![2.5, 6.0]);
    }

    #[test]
    fn window_engine_keeps_rust_state_across_bars() {
        let mut engine = WindowEngine::new(2, SessionOp::Mean).unwrap();
        let bar = |value| MarketBar::new(0, vec!["A".into()], vec![value]);
        assert_eq!(engine.update(&bar(1.0)).unwrap()[0], 1.0);
        assert_eq!(engine.update(&bar(2.0)).unwrap()[0], 1.5);
        assert_eq!(engine.update(&bar(3.0)).unwrap()[0], 2.5);
    }
}

#[cfg(all(test, feature = "nautilus"))]
mod nautilus_tests {
    use super::*;
    use nautilus_common::actor::{Actor, DataActor};
    use nautilus_common::actor::registry::{actor_exists, deregister_actor};
    use nautilus_model::data::{Bar, BarType};
    use nautilus_model::types::{Price, Quantity};
    use ustr::Ustr;

    #[test]
    fn native_callbacks_share_the_barrier_and_authoritative_boundaries() {
        use nautilus_model::data::CustomData;
        use std::sync::Arc;
        let json = r#"{"nodes":[{"kind":"column","index":0},
          {"kind":"boundary","index":0},
          {"kind":"session_reset","child":0,"boundary":1,"op":"mean","min_periods":1,"propagate_nan":false}],"outputs":[2]}"#;
        let mut actor = nautilus::FactorActor::from_plan_json("boundary-callback-test", 2, json).unwrap();
        actor.expect_products(&["A.B", "C.D"]);
        let make = |product: &str, price: &str, timestamp: u64| Bar::new(
            BarType::from(format!("{product}-1-MINUTE-LAST-EXTERNAL").as_str()),
            Price::from(price), Price::from(price), Price::from(price), Price::from(price),
            Quantity::from("1"), timestamp.into(), timestamp.into(),
        );
        actor.on_data(&CustomData::from_arc(Arc::new(crate::boundary::FactorBoundary {
            timestamp_ns: 1000, flags: vec![1, 1],
        }))).unwrap();
        actor.on_bar(&make("C.D", "10.0", 1000)).unwrap();
        assert!(actor.latest().is_empty(), "do not publish a partial cross-section");
        actor.on_bar(&make("A.B", "1.0", 1000)).unwrap();
        assert_eq!(actor.latest(), &[1.0, 10.0]);
        actor.on_data(&CustomData::from_arc(Arc::new(crate::boundary::FactorBoundary {
            timestamp_ns: 2000, flags: vec![0, 1],
        }))).unwrap();
        actor.on_bar(&make("A.B", "3.0", 2000)).unwrap();
        actor.on_bar(&make("C.D", "30.0", 2000)).unwrap();
        assert_eq!(actor.latest(), &[2.0, 30.0]);
        assert!(actor.queue_boundary(2000, &[1, 0]).is_err());
    }

    #[test]
    fn market_bar_from_bars_assembles_cross_section() {
        let make = |symbol: &str, close: &str| Bar::new(
            BarType::from(format!("{symbol}-1-MINUTE-LAST-EXTERNAL").as_str()),
            Price::from(close), Price::from(close), Price::from(close),
            Price::from(close), Quantity::from("1"), 1_000.into(), 1_000.into(),
        );
        let bar = nautilus::market_bar_from_bars(1_000, &[make("A.B", "1.0"), make("C.D", "2.0")]);
        assert_eq!(bar.products, vec!["A.B".to_string(), "C.D".to_string()]);
        assert_eq!(bar.values, vec![1.0, 2.0]);
    }

    #[test]
    fn factor_actor_satisfies_trader_actor_bounds() {
        use nautilus_common::component::Component;
        fn assert_bounds<T: Actor + DataActor + Component + std::fmt::Debug + 'static>() {}
        assert_bounds::<nautilus::FactorActor<crate::WindowEngine>>();
    }

    #[test]
    fn factor_actor_registers_with_nautilus() {
        let engine = MultiWindowEngine::new(vec![("mean".into(), 2, SessionOp::Mean)]).unwrap();
        let actor = nautilus::FactorActor::new("factor-actor-test", engine);
        actor.register();
        assert!(actor_exists(&Ustr::from("factor-actor-test")));
        deregister_actor(&Ustr::from("factor-actor-test"));
    }

    #[test]
    fn factor_actor_accepts_completed_cross_section_slice() {
        let json = r#"{"columns":["CLOSE"],"nodes":[{"kind":"column","index":0},{"kind":"cross","child":0,"op":"rank"}],"outputs":[1]}"#;
        let mut actor = nautilus::FactorActor::from_plan_json("factor-cross-test", 2, json).unwrap();
        let make = |symbol: &str, close: &str| Bar::new(
            BarType::from(format!("{symbol}-1-MINUTE-LAST-EXTERNAL").as_str()),
            Price::from(close), Price::from(close), Price::from(close),
            Price::from(close), Quantity::from("1"), 1_000.into(), 1_000.into(),
        );
        actor.handle_bars(&[make("A.B", "1.0"), make("C.D", "3.0")]);
        assert!(actor.last_error().is_none(), "{:?}", actor.last_error());
        assert_eq!(actor.latest(), &[0.0, 0.5]);
    }

    #[test]
    fn factor_actor_waits_for_complete_product_slice() {
        let json = r#"{"columns":["CLOSE"],"nodes":[{"kind":"column","index":0},{"kind":"cross","child":0,"op":"rank"}],"outputs":[1]}"#;
        let mut actor = nautilus::FactorActor::from_plan_json("factor-barrier-test", 2, json).unwrap();
        actor.expect_products(&["A.B", "C.D"]);
        let make = |symbol: &str, close: &str| Bar::new(
            BarType::from(format!("{symbol}-1-MINUTE-LAST-EXTERNAL").as_str()),
            Price::from(close), Price::from(close), Price::from(close),
            Price::from(close), Quantity::from("1"), 1_000.into(), 1_000.into(),
        );
        actor.on_completed_bar(&make("A.B", "1.0"));
        assert!(actor.latest().is_empty());
        actor.on_completed_bar(&make("A.B", "2.0"));
        assert!(actor.latest().is_empty(), "duplicate product must not complete a slice");
        assert_eq!(actor.pending_len(), 1);
        actor.on_completed_bar(&make("C.D", "3.0"));
        assert_eq!(actor.latest(), &[0.0, 0.5]);
        assert_eq!(actor.pending_len(), 0);
        let update = actor.last_update().unwrap();
        assert_eq!(update.timestamp_ns, 1_000);
        assert_eq!(update.products, vec!["A.B".to_string(), "C.D".to_string()]);
        assert_eq!(update.values, vec![0.0, 0.5]);
    }

    #[test]
    fn frozen_fields_preserve_product_order_and_slice_availability() {
        let json = r#"{"nodes":[{"kind":"column","index":0},{"kind":"column","index":1}],"outputs":[0,1]}"#;
        let mut actor = nautilus::FactorActor::from_plan_json("frozen-input-test",2,json).unwrap();
        actor.expect_products(&["Z", "A"]);
        let z = BarType::from("C.D-1-MINUTE-LAST-EXTERNAL");
        let a = BarType::from("A.B-1-MINUTE-LAST-EXTERNAL");
        actor.configure_bar_inputs(&[z,a], &["HIGH", "VOLUME"]).unwrap();
        let make = |bar_type, high, volume, available: u64| Bar::new(bar_type,
            Price::from("1.0"), Price::new(high,1), Price::from("1.0"),Price::from("1.0"),
            Quantity::new(volume,0),1000.into(),available.into());
        actor.on_completed_bar(&make(a,20.0,2.0,1005));
        actor.on_completed_bar(&make(z,10.0,1.0,1020));
        let update = actor.last_update().unwrap();
        assert_eq!(update.products, vec!["Z","A"]);
        assert_eq!(update.values, vec![10.0,20.0,1.0,2.0]);
        assert_eq!(update.timestamp_ns,1000);
        assert_eq!(update.available_at_ns,1020);
        assert!(actor.configure_bar_inputs(&[z,a], &["HIGH","VOLUME"]).is_err());
    }

    #[test]
    fn bridge_raw_extrema_select_the_same_parent_window_position() {
        let json = r#"{"nodes":[{"kind":"column","index":0},
          {"kind":"rolling","child":0,"window":5,"op":"argmax_raw","min_periods":1,"propagate_nan":false,"trunc_start":1,"trunc_end":2},
          {"kind":"rolling","child":0,"window":5,"op":"min","min_periods":1,"propagate_nan":false,"trunc_start_child":1,"trunc_end_child":1}],"outputs":[1,2]}"#;
        let values = [2.0,5.0,5.0,-2.0,9.0,1.0,0.0,3.0];
        let positions = [f64::NAN,1.0,1.0,1.0,1.0,1.0,2.0,1.0];
        let selected = [f64::NAN,5.0,5.0,5.0,5.0,5.0,9.0,9.0];
        for prefix in 1..=values.len() {
            let mut engine = crate::FactorPlanEngine::from_spec_json(json,1).unwrap();
            let mut out = Vec::new();
            for current in 0..prefix {
                let bar = crate::MarketBar::new(current as i64,vec!["A".into()],vec![values[current]]);
                engine.update_into(&bar,&mut out).unwrap();
                for (actual,expected) in out.iter().zip([positions[current],selected[current]]) {
                    assert!(actual.is_nan() && expected.is_nan() || *actual == expected, "row {current}: {actual} != {expected}");
                }
            }
        }
    }

    #[test]
    fn factor_actor_buffers_future_slice_without_mixing() {
        let json = r#"{"columns":["CLOSE"],"nodes":[{"kind":"column","index":0}],"outputs":[0]}"#;
        let mut actor = nautilus::FactorActor::from_plan_json("factor-time-test", 2, json).unwrap();
        actor.expect_products(&["A.B", "C.D"]);
        let make = |symbol: &str, timestamp: u64| Bar::new(
            BarType::from(format!("{symbol}-1-MINUTE-LAST-EXTERNAL").as_str()),
            Price::from("1.0"), Price::from("1.0"), Price::from("1.0"),
            Price::from("1.0"), Quantity::from("1"), timestamp.into(), timestamp.into(),
        );
        actor.on_completed_bar(&make("A.B", 1_000));
        actor.on_completed_bar(&make("C.D", 2_000));
        assert_eq!(actor.pending_len(), 2);
        assert!(actor.last_error().is_none());
        actor.on_completed_bar(&make("A.B", 2_000));
        actor.on_completed_bar(&make("C.D", 1_000));
        assert_eq!(actor.pending_len(), 0);
        assert_eq!(actor.last_update().unwrap().timestamp_ns, 2_000);
    }

    #[test]
    fn factor_actor_expires_stale_slices_and_bounds_future_buffer() {
        let json = r#"{"columns":["CLOSE"],"nodes":[{"kind":"column","index":0}],"outputs":[0]}"#;
        let mut actor = nautilus::FactorActor::from_plan_json("factor-expire-test", 2, json).unwrap();
        actor.expect_products(&["A.B", "C.D"]);
        actor.set_max_future_slices(1);
        let make = |symbol: &str, timestamp: u64| Bar::new(
            BarType::from(format!("{symbol}-1-MINUTE-LAST-EXTERNAL").as_str()),
            Price::from("1.0"), Price::from("1.0"), Price::from("1.0"),
            Price::from("1.0"), Quantity::from("1"), timestamp.into(), timestamp.into(),
        );
        actor.on_completed_bar(&make("A.B", 1_000));
        actor.on_completed_bar(&make("C.D", 2_000));
        actor.on_completed_bar(&make("A.B", 3_000));
        assert!(actor.last_error().unwrap().contains("future slice limit"));
        actor.expire_before(2_000);
        assert_eq!(actor.pending_len(), 1);
    }

    #[test]
    fn factor_actor_publishes_timestamped_update_to_sink() {
        let json = r#"{"columns":["CLOSE"],"nodes":[{"kind":"column","index":0}],"outputs":[0]}"#;
        let mut actor = nautilus::FactorActor::from_plan_json("factor-sink-test", 1, json).unwrap();
        let seen = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
        let target = seen.clone();
        actor.set_update_sink(move |update| target.lock().unwrap().push(update.timestamp_ns));
        let bar = Bar::new(
            BarType::from("A.B-1-MINUTE-LAST-EXTERNAL"),
            Price::from("1.0"), Price::from("1.0"), Price::from("1.0"),
            Price::from("1.0"), Quantity::from("1"), 1_000.into(), 1_000.into(),
        );
        actor.on_bar(&bar).unwrap();
        assert_eq!(*seen.lock().unwrap(), vec![1_000]);
        actor.publish_last_update("factor.updates.test");
    }

    #[test]
    fn factor_actor_reports_expired_incomplete_slices() {
        let json = r#"{"columns":["CLOSE"],"nodes":[{"kind":"column","index":0}],"outputs":[0]}"#;
        let mut actor = nautilus::FactorActor::from_plan_json("factor-stale-test", 2, json).unwrap();
        actor.expect_products(&["A.B", "C.D"]);
        let bar = Bar::new(
            BarType::from("A.B-1-MINUTE-LAST-EXTERNAL"),
            Price::from("1.0"), Price::from("1.0"), Price::from("1.0"),
            Price::from("1.0"), Quantity::from("1"), 1_000.into(), 1_000.into(),
        );
        actor.on_completed_bar(&bar);
        assert_eq!(actor.expire_stale(5_000, 1_000), 1);
        assert_eq!(actor.pending_len(), 0);
        assert!(actor.last_error().unwrap().contains("stale"));
    }

    #[test]
    fn factor_actor_timer_expires_incomplete_slices() {
        let json = r#"{"columns":["CLOSE"],"nodes":[{"kind":"column","index":0}],"outputs":[0]}"#;
        let mut actor = nautilus::FactorActor::from_plan_json("factor-timer-test", 2, json).unwrap();
        actor.expect_products(&["A.B", "C.D"]);
        actor.set_barrier_grace(1_000);
        let bar = Bar::new(
            BarType::from("A.B-1-MINUTE-LAST-EXTERNAL"),
            Price::from("1.0"), Price::from("1.0"), Price::from("1.0"),
            Price::from("1.0"), Quantity::from("1"), 1_000.into(), 1_000.into(),
        );
        actor.on_completed_bar(&bar);
        assert_eq!(actor.on_timer(3_000), 1);
        assert_eq!(actor.pending_len(), 0);
    }

    #[test]
    fn expire_before_keeps_pending_slots_allocated() {
        let json = r#"{"columns":["CLOSE"],"nodes":[{"kind":"column","index":0}],"outputs":[0]}"#;
        let mut actor = nautilus::FactorActor::from_plan_json("factor-expire-test", 2, json).unwrap();
        actor.expect_products(&["A.B", "C.D"]);
        let first = Bar::new(
            BarType::from("A.B-1-MINUTE-LAST-EXTERNAL"),
            Price::from("1.0"), Price::from("1.0"), Price::from("1.0"),
            Price::from("1.0"), Quantity::from("1"), 1_000.into(), 1_000.into(),
        );
        actor.on_completed_bar(&first);
        actor.expire_before(2_000);
        let second = Bar::new(
            BarType::from("A.B-1-MINUTE-LAST-EXTERNAL"),
            Price::from("1.0"), Price::from("1.0"), Price::from("1.0"),
            Price::from("1.0"), Quantity::from("1"), 2_000.into(), 2_000.into(),
        );
        actor.on_completed_bar(&second);
        assert_eq!(actor.pending_len(), 1);
    }

    #[test]
    fn factor_actor_surfaces_engine_errors() {
        let json = r#"{"columns":["CLOSE"],"nodes":[{"kind":"column","index":0}],"outputs":[0]}"#;
        let mut actor = nautilus::FactorActor::from_plan_json("factor-error-test", 2, json).unwrap();
        let bar = Bar::new(
            BarType::from("A.B-1-MINUTE-LAST-EXTERNAL"),
            Price::from("1.0"), Price::from("1.0"), Price::from("1.0"),
            Price::from("1.0"), Quantity::from("10"), 1_000.into(), 1_000.into(),
        );
        let _ = actor.on_bar(&bar);
        assert!(actor.last_error().is_some());
    }

    #[test]
    fn factor_actor_loads_public_plan_json() {
        let json = r#"{"columns":["CLOSE"],"nodes":[{"kind":"column","index":0},{"kind":"rolling","child":0,"window":2,"op":"mean","min_periods":1,"propagate_nan":true}],"outputs":[1]}"#;
        let mut actor = nautilus::FactorActor::from_plan_json("factor-json-test", 1, json).unwrap();
        let bar = Bar::new(
            BarType::from("A.B-1-MINUTE-LAST-EXTERNAL"),
            Price::from("1.0"), Price::from("1.0"), Price::from("1.0"),
            Price::from("1.0"), Quantity::from("10"), 1_000.into(), 1_000.into(),
        );
        actor.on_bar(&bar).unwrap();
        assert_eq!(actor.latest(), &[1.0]);
    }

    #[test]
    fn factor_actor_consumes_nautilus_bar() {
        let engine = MultiWindowEngine::new(vec![("mean".into(), 2, SessionOp::Mean)]).unwrap();
        let mut actor = nautilus::FactorActor::new("factor-actor-bar-test", engine);
        let bar = Bar::new(
            BarType::from("A.B-1-MINUTE-LAST-EXTERNAL"),
            Price::from("1.0"), Price::from("1.0"), Price::from("1.0"),
            Price::from("1.0"), Quantity::from("10"), 1_000.into(), 1_000.into(),
        );
        actor.on_bar(&bar).unwrap();
        assert_eq!(actor.latest(), &[1.0]);
    }
}

#[cfg(all(test, feature = "nautilus-backtest"))]
mod backtest_actor_tests {
    use nautilus_backtest::config::BacktestEngineConfig;
    use nautilus_backtest::engine::BacktestEngine;

    use crate::{SessionOp, WindowEngine};
    use crate::nautilus::FactorActor;

    #[test]
    fn factor_actor_can_be_added_to_backtest_engine() {
        let mut engine = BacktestEngine::new(BacktestEngineConfig::default()).unwrap();
        let actor = FactorActor::new("factor-engine-test", WindowEngine::new(2, SessionOp::Mean).unwrap());
        engine.add_actor(actor).unwrap();
        assert_eq!(engine.kernel().trader.borrow().actor_count(), 1);
    }
}

#[cfg(test)]
mod batch_product_lane_tests {
    use super::*;

    #[test]
    fn batch_product_lanes_match_sequential_products() {
        let specs = vec![
            plan::ExprSpec::Column(0),
            plan::ExprSpec::Rolling { child: 0, window: 2, op: alpha_algo::SessionOp::Mean,
                min_periods: 1, propagate_nan: false, trunc_start: -1, trunc_end: -1,
                trunc_start_child: None, trunc_end_child: None },
        ];
        let mut parallel = ProductParallelPlanEngine::new(8, specs.clone(), vec![1]).unwrap();
        let products: Vec<String> = (0..8).map(|index| format!("P{index}")).collect();
        let first: Vec<f64> = (0..8).map(|value| value as f64).collect();
        let second: Vec<f64> = (0..8).map(|value| value as f64 * 3.0).collect();
        let bars = vec![
            MarketBar::new(1, products.clone(), first.clone()),
            MarketBar::new(2, products, second.clone()),
        ];
        let out = parallel.update_batch(&bars).unwrap();
        for product in 0..8 {
            assert_eq!(out[0][product], first[product]);
            assert_eq!(out[1][product], (first[product] + second[product]) / 2.0);
        }
    }
}
