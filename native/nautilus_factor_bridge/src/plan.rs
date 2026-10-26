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

    pub fn update_into(&mut self, bar: &MarketBar, out: &mut Vec<f64>) -> Result<(), alpha_algo::Error> {
        if bar.term_curves.is_empty() {
            self.inner.update_into(bar.timestamp_ns, &bar.values, out)
        } else {
            let values = self.inner.update_with_curves(bar.timestamp_ns, &bar.values, &bar.term_curves)?;
            out.clear();
            out.extend(values);
            Ok(())
        }
    }
}

impl FactorEngine for FactorPlanEngine {
    type Error = alpha_algo::Error;

    fn update(&mut self, bar: &MarketBar) -> Result<Vec<f64>, Self::Error> {
        self.inner.update_at(bar.timestamp_ns, &bar.values)
    }
}
