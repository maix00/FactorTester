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
}

impl FactorEngine for FactorPlanEngine {
    type Error = alpha_algo::Error;

    fn update(&mut self, bar: &MarketBar) -> Result<Vec<f64>, Self::Error> {
        self.inner.update_at(bar.timestamp_ns, &bar.values)
    }
}
