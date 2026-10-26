//! Factor execution bridge.
//!
//! Nautilus core does not depend on this crate.  A Nautilus actor/plugin
//! depends on the bridge (or the bridge depends on the optional Nautilus
//! feature), keeping py-alpha-lib independent.

use alpha_algo::{IntervalKernel, SessionOp};

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
    //! Placeholder for the concrete Nautilus Bar adapter.  The dependency is
    //! feature-gated so Nautilus core never depends on this crate.
    pub use nautilus_core as core;
}

#[cfg(test)]
mod tests {
    use super::*;

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
