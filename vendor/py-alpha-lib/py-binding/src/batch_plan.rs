//! PyO3 adapter over the pure Rust `alpha_algo::PanelPlan`.
use numpy::{IntoPyArray, PyReadonlyArray1};
use pyo3::prelude::*;

#[pyclass]
pub(crate) struct BatchPlan {
    inner: alpha_algo::PanelPlan,
}

#[pymethods]
impl BatchPlan {
    #[new]
    fn new() -> Self {
        Self { inner: alpha_algo::PanelPlan::new() }
    }

    fn grid(&mut self, times: PyReadonlyArray1<i64>, days: PyReadonlyArray1<i64>, observed: PyReadonlyArray1<u8>) -> PyResult<usize> {
        Ok(self.inner.grid(times.as_slice()?, days.as_slice()?, observed.as_slice()?)?)
    }

    fn add(&mut self, op: String, children: Vec<usize>, params: Vec<f64>, indices: Vec<i64>, grid: usize) -> PyResult<usize> {
        Ok(self.inner.add(op, children, params, indices, grid)?)
    }

    #[staticmethod]
    fn asof_indices(source: PyReadonlyArray1<i64>, target: PyReadonlyArray1<i64>) -> PyResult<Vec<i64>> {
        Ok(alpha_algo::PanelPlan::asof_indices(source.as_slice()?, target.as_slice()?)?)
    }

    #[staticmethod]
    fn signal_indices(keys: PyReadonlyArray1<i64>, times: PyReadonlyArray1<i64>, multiple: usize, basepoint: &str, mask: Vec<bool>, gap: Option<i64>) -> PyResult<Vec<usize>> {
        Ok(alpha_algo::PanelPlan::signal_indices(keys.as_slice()?, times.as_slice()?, multiple, basepoint, mask, gap)?)
    }

    fn execute_panel(&self, py: Python<'_>, columns: Vec<PyReadonlyArray1<f64>>, outputs: Vec<usize>, products: usize) -> PyResult<Vec<Py<numpy::PyArray1<f64>>>> {
        let columns: Vec<&[f64]> = columns.iter().map(|c| c.as_slice()).collect::<Result<_, _>>()?;
        let result = self.inner.execute_panel(&columns, &outputs, products)?;
        Ok(result.into_iter().map(|values| values.into_pyarray(py).unbind()).collect())
    }
}
