//! Bridge adapter over the pure Rust `alpha_algo::FactorPlanKernel`.

pub use alpha_algo::{BinaryOp, CrossOp, ExprSpec};

use crate::{FactorEngine, MarketBar};

pub struct FactorPlanEngine {
    inner: alpha_algo::FactorPlanKernel,
}

impl FactorPlanEngine {
    pub fn new(products: usize, specs: Vec<ExprSpec>, outputs: Vec<usize>) -> Result<Self, alpha_algo::Error> {
        Ok(Self { inner: alpha_algo::FactorPlanKernel::new(products, specs, outputs)? })
    }

    pub fn from_spec_json(json: &str, products: usize) -> Result<Self, alpha_algo::Error> {
        Ok(Self { inner: alpha_algo::FactorPlanKernel::from_spec_json(json, products)? })
    }

    pub fn node_keys(&self) -> &[String] { self.inner.node_keys() }
    pub fn boundary_channels(&self) -> usize { self.inner.boundary_channels() }
    pub fn input_fields(&self) -> usize { self.inner.input_fields() }

    pub fn update_into(&mut self, bar: &MarketBar, out: &mut Vec<f64>) -> Result<(), alpha_algo::Error> {
        self.inner.update_into_context(bar.timestamp_ns, &bar.values, &bar.boundaries, &bar.term_curves, out)
    }
}

impl FactorEngine for FactorPlanEngine {
    type Error = alpha_algo::Error;

    fn update(&mut self, bar: &MarketBar) -> Result<Vec<f64>, Self::Error> {
        let mut out = Vec::new();
        self.update_into(bar, &mut out)?;
        Ok(out)
    }

    fn update_into(&mut self, bar: &MarketBar, out: &mut Vec<f64>) -> Result<(), Self::Error> {
        FactorPlanEngine::update_into(self, bar, out)
    }
}
