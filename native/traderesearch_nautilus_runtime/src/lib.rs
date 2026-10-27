//! Composition only: one Nautilus binary/registry with independent factor bridge.
#![cfg_attr(target_vendor = "apple", allow(linker_messages))]
use nautilus_backtest::python::engine::PyBacktestEngine;
use nautilus_factor_bridge::{
    family::ConsumerSpec,
    runtime::{FamilyRuntimeHandle, install_family_runtime},
};
use nautilus_model::data::BarType;
use pyo3::{exceptions::PyRuntimeError, prelude::*};

#[pyclass(unsendable)]
struct FactorRuntimeHandle {
    inner: FamilyRuntimeHandle,
}

#[pymethods]
impl FactorRuntimeHandle {
    fn latest_output(&self, output: usize) -> PyResult<(i64, i64, Vec<f64>)> {
        self.inner.latest_output(output).map_err(|e| PyRuntimeError::new_err(e.to_string()))
    }

    fn raise_if_failed(&self) -> PyResult<()> {
        self.inner
            .raise_if_failed()
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))
    }
    fn ensure_success(&self) -> PyResult<()> {
        self.inner
            .ensure_success()
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))
    }
    #[getter]
    fn slice_count(&self) -> usize {
        self.inner.slice_count()
    }
    #[getter]
    fn rank_passes(&self) -> usize {
        self.inner.rank_passes()
    }
    #[getter]
    fn consumer_strategy_ids(&self) -> Vec<(String,String)> {
        self.inner.consumer_strategy_ids.clone()
    }
    #[getter]
    fn node_count(&self) -> usize {
        self.inner.node_count
    }
    #[getter]
    fn consumer_counts(&self) -> Vec<usize> {
        self.inner.consumer_counts()
    }
}

#[pyfunction]
#[pyo3(signature=(engine,plan_json,products,bar_types,consumers_json,calendar_json="[]",trace_path=None))]
fn attach_factor_family(
    mut engine: PyRefMut<'_, PyBacktestEngine>,
    plan_json: &str,
    products: Vec<String>,
    bar_types: Vec<String>,
    consumers_json: &str,
    calendar_json: &str,
    trace_path: Option<&str>,
) -> PyResult<FactorRuntimeHandle> {
    let types = bar_types
        .iter()
        .map(|value| value.parse::<BarType>())
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    let consumers: Vec<ConsumerSpec> =
        serde_json::from_str(consumers_json).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    let calendar =
        serde_json::from_str(calendar_json).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    let inner = install_family_runtime(
        engine.inner_mut(),
        plan_json,
        &products,
        &types,
        consumers,
        calendar,
        trace_path,
    )
    .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    Ok(FactorRuntimeHandle { inner })
}

#[pymodule]
fn _libnautilus(py: Python<'_>, module: &Bound<'_, PyModule>) -> PyResult<()> {
    nautilus_pyo3::_libnautilus(py, module)?;
    module.add_function(wrap_pyfunction!(attach_factor_family, module)?)?;
    module.add_class::<FactorRuntimeHandle>()?;
    Ok(())
}
