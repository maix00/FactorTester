//! Factor execution bridge.
//!
//! Nautilus core does not depend on this crate.  A Nautilus actor/plugin
//! depends on the bridge (or the bridge depends on the optional Nautilus
//! feature), keeping py-alpha-lib independent.

use alpha_algo::{IntervalKernel, SessionOp};

pub mod plan;
pub use plan::{BinaryOp, CrossOp, ExprSpec, FactorPlanEngine};

#[derive(Clone, Debug)]
pub struct MarketBar {
    pub timestamp_ns: i64,
    pub products: Vec<String>,
    pub values: Vec<f64>,
}

impl MarketBar {
    pub fn new(timestamp_ns: i64, products: Vec<String>, values: Vec<f64>) -> Self {
        Self { timestamp_ns, products, values }
    }
}

#[derive(Clone, Debug)]
pub struct FactorUpdate {
    pub timestamp_ns: i64,
    pub products: Vec<String>,
    pub values: Vec<f64>,
}

pub trait FactorEngine {
    type Error;
    fn warmup(&mut self) -> Result<(), Self::Error> { Ok(()) }
    fn update(&mut self, bar: &MarketBar) -> Result<Vec<f64>, Self::Error>;
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

    use std::any::Any;
    use std::fmt;

    use nautilus_common::actor::Actor;
    use nautilus_model::data::Bar;
    use ustr::Ustr;

    use crate::{FactorEngine, FactorUpdate, MarketBar};

    /// Minimal Nautilus actor that owns the Rust factor engine and consumes
    /// `Bar` messages.  Registration with a trader is the caller's job.
    pub struct FactorActor<E> {
        id: Ustr,
        engine: E,
        latest: Vec<f64>,
        last_error: Option<String>,
        expected_products: Vec<String>,
        pending_bars: std::collections::BTreeMap<String, Bar>,
        last_update: Option<FactorUpdate>,
        pending_timestamp: Option<i64>,
        future_slices: std::collections::BTreeMap<i64, std::collections::BTreeMap<String, Bar>>,
        max_future_slices: usize,
        sink: Option<Box<dyn Fn(&FactorUpdate) + Send>>,
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
            Self {
                id: Ustr::from(actor_id), engine, latest: Vec::new(), last_error: None,
                expected_products: Vec::new(),
                pending_bars: std::collections::BTreeMap::new(),
                pending_timestamp: None,
                future_slices: std::collections::BTreeMap::new(),
                max_future_slices: 64,
                sink: None,
                last_update: None,
            }
        }

        pub fn latest(&self) -> &[f64] { &self.latest }

        pub fn last_error(&self) -> Option<&str> { self.last_error.as_deref() }

        pub fn set_max_future_slices(&mut self, limit: usize) { self.max_future_slices = limit.max(1); }

        pub fn set_update_sink(&mut self, sink: impl Fn(&FactorUpdate) + Send + 'static) {
            self.sink = Some(Box::new(sink));
        }

        fn publish(&self) {
            if let (Some(sink), Some(update)) = (self.sink.as_ref(), self.last_update.as_ref()) {
                sink(update);
            }
        }

        /// Drop slices older than ``now_ns - grace_ns``; report dropped work.
        pub fn expire_stale(&mut self, now_ns: i64, grace_ns: i64) -> usize {
            let cutoff = now_ns.saturating_sub(grace_ns);
            let before = self.pending_len();
            self.future_slices = self.future_slices.split_off(&cutoff);
            if self.pending_timestamp.is_some_and(|timestamp| timestamp < cutoff) {
                self.pending_bars.clear();
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
            if self.pending_timestamp.is_some_and(|timestamp| timestamp < timestamp_ns) {
                self.pending_bars.clear();
                self.pending_timestamp = None;
            }
        }

        pub fn pending_len(&self) -> usize {
            self.pending_bars.len() + self.future_slices.values().map(|slice| slice.len()).sum::<usize>()
        }

        pub fn last_update(&self) -> Option<&FactorUpdate> { self.last_update.as_ref() }

        pub fn expect_products(&mut self, products: &[&str]) {
            self.expected_products = products.iter().map(|product| product.to_string()).collect();
            self.expected_products.sort();
        }

        /// Collect one bar per frozen product; update only when every product arrived.
        pub fn on_completed_bar(&mut self, bar: &Bar) {
            if self.expected_products.is_empty() {
                self.handle(bar);
                return;
            }
            let product = bar.bar_type.instrument_id().to_string();
            if !self.expected_products.contains(&product) {
                self.last_error = Some(format!("unexpected product {product}"));
                return;
            }
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
                    self.future_slices.entry(timestamp).or_default().insert(product, bar.clone());
                    return;
                }
            } else {
                self.pending_timestamp = Some(timestamp);
            }
            self.pending_bars.insert(product, bar.clone());
            if self.pending_bars.len() == self.expected_products.len() {
                self.flush_slice();
            }
        }

        fn flush_slice(&mut self) {
            let Some(timestamp) = self.pending_timestamp else { return };
            if self.pending_bars.len() != self.expected_products.len() { return; }
            let bars: Vec<Bar> = self.expected_products.iter()
                .map(|product| self.pending_bars.remove(product).unwrap())
                .collect();
            let market = crate::nautilus::market_bar_from_bars(timestamp, &bars);
            match self.engine.update(&market) {
                Ok(values) => {
                    self.latest = values.clone();
                    self.last_update = Some(FactorUpdate {
                        timestamp_ns: timestamp,
                        products: market.products.clone(),
                        values,
                    });
                    self.last_error = None;
                    self.publish();
                }
                Err(error) => self.last_error = Some(error.to_string()),
            }
            self.pending_bars.clear();
            self.pending_timestamp = None;
            while let Some((&next, slice)) = self.future_slices.iter().next() {
                if slice.len() != self.expected_products.len() { break; }
                let slice = self.future_slices.remove(&next).unwrap();
                self.pending_bars = slice;
                self.pending_timestamp = Some(next);
                self.flush_slice();
            }
        }

        /// Assemble one completed cross-sectional slice and update once.
        pub fn handle_bars(&mut self, bars: &[Bar]) {
            let Some(first) = bars.first() else { return };
            let bar = crate::nautilus::market_bar_from_bars(first.ts_event.as_u64() as i64, bars);
            match self.engine.update(&bar) {
                Ok(values) => { self.latest = values; self.last_error = None; }
                Err(error) => self.last_error = Some(error.to_string()),
            }
        }

        /// Register this actor in Nautilus' thread-local actor registry.
        pub fn register(self) -> std::rc::Rc<std::cell::UnsafeCell<Self>> {
            nautilus_common::actor::registry::register_actor(self)
        }
    }

    impl<E: FactorEngine + 'static> Actor for FactorActor<E>
    where E::Error: std::fmt::Display, {
        fn id(&self) -> Ustr { self.id }

        fn handle(&mut self, msg: &dyn Any) {
            if let Some(bar) = msg.downcast_ref::<Bar>() {
                let bar = MarketBar::from(bar);
                match self.engine.update(&bar) {
                    Ok(values) => {
                        self.latest = values.clone();
                        self.last_update = Some(FactorUpdate {
                            timestamp_ns: bar.timestamp_ns,
                            products: bar.products.clone(),
                            values,
                        });
                        self.last_error = None;
                        self.publish();
                    }
                    Err(error) => self.last_error = Some(error.to_string()),
                }
            }
        }

        fn as_any(&self) -> &dyn Any { self }
    }

    impl FactorActor<crate::plan::FactorPlanEngine> {
        /// Build an actor directly from the public `alpha.factor` plan JSON.
        pub fn from_plan_json(actor_id: &str, products: usize, json: &str) -> Result<Self, alpha_algo::Error> {
            let engine = crate::plan::FactorPlanEngine::from_spec_json(json, products)?;
            Ok(Self::new(actor_id, engine))
        }
    }

    /// Assemble a cross-sectional bar from one Nautilus `Bar` per product.
    pub fn market_bar_from_bars(timestamp_ns: i64, bars: &[Bar]) -> MarketBar {
        let products = bars.iter().map(|bar| bar.bar_type.instrument_id().to_string()).collect();
        let values = bars.iter().map(|bar| bar.close.as_f64()).collect();
        MarketBar::new(timestamp_ns, products, values)
    }

    impl From<&Bar> for MarketBar {
        fn from(bar: &Bar) -> Self {
            Self {
                timestamp_ns: bar.ts_event.as_u64() as i64,
                products: vec![bar.bar_type.instrument_id().to_string()],
                values: vec![bar.close.as_f64()],
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn product_parallel_plan_updates_products_independently() {
        let specs = vec![
            plan::ExprSpec::Column(0),
            plan::ExprSpec::Rolling { child: 0, window: 2, op: SessionOp::Mean, min_periods: 1, propagate_nan: true },
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
    use nautilus_common::actor::Actor;
    use nautilus_common::actor::registry::{actor_exists, deregister_actor};
    use nautilus_model::data::{Bar, BarType};
    use nautilus_model::types::{Price, Quantity};
    use ustr::Ustr;

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
        actor.on_completed_bar(&make("C.D", "3.0"));
        assert_eq!(actor.latest(), &[0.0, 0.5]);
        assert_eq!(actor.pending_len(), 0);
        let update = actor.last_update().unwrap();
        assert_eq!(update.timestamp_ns, 1_000);
        assert_eq!(update.products, vec!["A.B".to_string(), "C.D".to_string()]);
        assert_eq!(update.values, vec![0.0, 0.5]);
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
        actor.handle(&bar);
        assert_eq!(*seen.lock().unwrap(), vec![1_000]);
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
    fn factor_actor_surfaces_engine_errors() {
        let json = r#"{"columns":["CLOSE"],"nodes":[{"kind":"column","index":0}],"outputs":[0]}"#;
        let mut actor = nautilus::FactorActor::from_plan_json("factor-error-test", 2, json).unwrap();
        let bar = Bar::new(
            BarType::from("A.B-1-MINUTE-LAST-EXTERNAL"),
            Price::from("1.0"), Price::from("1.0"), Price::from("1.0"),
            Price::from("1.0"), Quantity::from("10"), 1_000.into(), 1_000.into(),
        );
        actor.handle(&bar);
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
        actor.handle(&bar);
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
        actor.handle(&bar);
        assert_eq!(actor.latest(), &[1.0]);
    }
}
