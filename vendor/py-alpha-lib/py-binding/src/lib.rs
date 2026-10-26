// Copyright 2026 MSD-RS Project LiJia
// SPDX-License-Identifier: BSD-2-Clause

use std::sync::{LazyLock, RwLock};

use alpha_algo::Context;
use pyo3::prelude::*;
use numpy::PyArrayMethods;

mod batch_plan;
use batch_plan::BatchPlan;

static _ALGO_CTX_: LazyLock<RwLock<Context>> = LazyLock::new(|| RwLock::new(Context::default()));

mod algo_impl {
  use log::debug;
  use numpy::{IntoPyArray, PyArray1, PyReadonlyArray1, PyReadwriteArray1};
  use pyo3::{exceptions::PyValueError, prelude::*, types::PyList};
  use rayon::iter::{IndexedParallelIterator, IntoParallelIterator, ParallelIterator};
  use rayon::slice::ParallelSliceMut;

  use crate::_ALGO_CTX_;

  use alpha_algo::*;

  fn ctx<'py>(_py: Python<'py>) -> Context {
    let ctx = match _ALGO_CTX_.try_read() {
      Ok(ctx) => ctx.clone(),
      Err(_e) => Context::default(),
    };
    debug!("current {}", ctx);
    ctx
  }

  fn interval_op(name: &str, quantile: Option<f64>) -> PyResult<alpha_algo::SessionOp> {
    use alpha_algo::SessionOp;
    Ok(match name {
      "sum" => SessionOp::Sum, "mean" => SessionOp::Mean,
      "var" => SessionOp::Var, "std" => SessionOp::Std,
      "min" => SessionOp::Min, "max" => SessionOp::Max,
      "skew" => SessionOp::Skew, "argmin" => SessionOp::Argmin,
      "argmax" => SessionOp::Argmax, "rank" => SessionOp::Rank,
      "mad" => SessionOp::Mad,
      "median" | "quantile" => SessionOp::Quantile(quantile.unwrap_or(0.5)),
      other => return Err(pyo3::exceptions::PyValueError::new_err(
        format!("unsupported interval op: {other}")
      )),
    })
  }

  #[pyfunction]
  #[pyo3(signature = (values, span, min_periods=1, propagate_nan=true))]
  pub fn interval_ema(
    py: Python<'_>, values: PyReadonlyArray1<f64>, span: usize,
    min_periods: usize, propagate_nan: bool,
  ) -> PyResult<Py<PyArray1<f64>>> {
    let values = values.as_slice()?;
    let mut state = alpha_algo::EmaState::new(span)
      .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?
      .with_semantics(min_periods, propagate_nan);
    Ok(values.iter().copied().map(|value| state.update(value))
      .collect::<Vec<_>>().into_pyarray(py).unbind())
  }

  #[pyfunction]
  #[pyo3(signature = (values, count, include_current=true, nearest=true, default_scope=true, default=0.0))]
  pub fn bar_since(
    py: pyo3::Python<'_>, values: numpy::PyReadonlyArray1<f64>, count: usize,
    include_current: bool, nearest: bool, default_scope: bool, default: f64,
  ) -> pyo3::PyResult<pyo3::Py<numpy::PyArray1<f64>>> {
    use numpy::IntoPyArray;
    let values = values.as_slice()?;
    let count = count.max(1);
    let mut out = vec![f64::NAN; values.len()];
    let mut first: Option<usize> = None;
    let mut last: Option<usize> = None;
    let mut base = 0usize;
    for index in 0..values.len() {
      if index % count == 0 { base = index; first = None; last = None; }
      let truth = values[index].is_finite() && values[index] != 0.0;
      if truth && include_current {
        if first.is_none() { first = Some(index); }
        last = Some(index);
      }
      let matched = if nearest { last } else { first };
      out[index] = match matched {
        Some(hit) => (index - hit) as f64,
        None => if default_scope { (index - base) as f64 } else { default },
      };
      if truth && !include_current {
        if first.is_none() { first = Some(index); }
        last = Some(index);
      }
    }
    Ok(out.into_pyarray(py).unbind())
  }

  #[pyfunction]
  pub fn cross_sectional(
    py: pyo3::Python<'_>, columns: Vec<numpy::PyReadonlyArray1<f64>>, op: &str,
  ) -> pyo3::PyResult<Vec<pyo3::Py<numpy::PyArray1<f64>>>> {
    use numpy::IntoPyArray;
    let slices: Vec<&[f64]> = columns.iter().map(|c| c.as_slice()).collect::<Result<_, _>>()?;
    let rows = slices.first().map(|c| c.len()).unwrap_or(0);
    let width = slices.len();
    if slices.iter().any(|c| c.len() != rows) {
      return Err(pyo3::exceptions::PyValueError::new_err("cross_sectional length mismatch"));
    }
    let mut output = vec![vec![f64::NAN; rows]; width];
    for row in 0..rows {
      let mut values: Vec<(usize, f64)> = (0..width)
        .map(|column| (column, slices[column][row]))
        .filter(|(_, value)| value.is_finite())
        .collect();
      if values.is_empty() { continue; }
      match op {
        "cs_zscore" => {
          let n = values.len() as f64;
          let mean = values.iter().map(|(_, value)| *value).sum::<f64>() / n;
          let variance = values.iter().map(|(_, value)| (*value - mean).powi(2)).sum::<f64>() / n;
          let std = variance.sqrt();
          if std > 0.0 {
            for (column, value) in values { output[column][row] = (value - mean) / std; }
          } else {
            for (column, _) in values { output[column][row] = 0.0; }
          }
        }
        "cs_rank" => {
          values.sort_by(|a, b| a.1.total_cmp(&b.1));
          let n = values.len() as f64;
          for (rank, (column, _)) in values.into_iter().enumerate() {
            output[column][row] = (rank as f64 + 1.0) / n - 0.5;
          }
        }
        other => return Err(pyo3::exceptions::PyValueError::new_err(
          format!("cross_sectional does not support {other}")
        )),
      }
    }
    Ok(output.into_iter().map(|values| values.into_pyarray(py).unbind()).collect())
  }

  #[pyfunction]
  #[pyo3(signature = (values, starts, ends, op, quantile=None, window=None, min_periods=1, propagate_nan=false))]
  pub fn interval_rolling(
    py: Python<'_>, values: PyReadonlyArray1<f64>, starts: PyReadonlyArray1<u64>,
    ends: PyReadonlyArray1<u64>, op: &str, quantile: Option<f64>,
    window: Option<usize>, min_periods: usize, propagate_nan: bool,
  ) -> PyResult<Py<PyArray1<f64>>> {
    let values = values.as_slice()?;
    let starts = starts.as_slice()?;
    let ends = ends.as_slice()?;
    let fixed = window.is_some();
    if !fixed && (values.len() != starts.len() || values.len() != ends.len()) {
      return Err(pyo3::exceptions::PyValueError::new_err(
        "interval_rolling length mismatch"
      ));
    }
    let op = interval_op(op, quantile)?;
    let window = window.unwrap_or(1).max(1);
    if fixed && matches!(
      op, alpha_algo::SessionOp::Sum | alpha_algo::SessionOp::Mean
        | alpha_algo::SessionOp::Var | alpha_algo::SessionOp::Std
        | alpha_algo::SessionOp::Skew
    ) {
      // SumMoments family: one independent sliding state per chunk, like upstream.
      #[derive(Clone, Copy)]
      enum Moment { Sum, Mean, Var, Std, Skew }
      let family = match op {
        alpha_algo::SessionOp::Mean => Moment::Mean,
        alpha_algo::SessionOp::Var => Moment::Var,
        alpha_algo::SessionOp::Std => Moment::Std,
        alpha_algo::SessionOp::Skew => Moment::Skew,
        _ => Moment::Sum,
      };
      let n = values.len();
      {
        const CHUNK: usize = 65_536;
        let mut out = vec![f64::NAN; n];
        out.par_chunks_mut(CHUNK).enumerate().for_each(|(chunk_index, chunk)| {
          let chunk_start = chunk_index * CHUNK;
          let (mut total, mut square, mut cube, mut count) = (0.0f64, 0.0f64, 0.0f64, 0usize);
          for value in &values[chunk_start.saturating_sub(window)..chunk_start] {
            if value.is_finite() {
              total += *value; square += *value * *value; cube += *value * *value * *value;
              count += 1;
            }
          }
          for (offset, slot) in chunk.iter_mut().enumerate() {
            let index = chunk_start + offset;
            let value = values[index];
            if value.is_finite() {
              total += value; square += value * value; cube += value * value * value;
              count += 1;
            }
            if index >= window {
              let old = values[index - window];
              if old.is_finite() {
                total -= old; square -= old * old; cube -= old * old * old;
                count -= 1;
              }
            }
            let width = (index + 1).min(window);
            *slot = if count < min_periods || (propagate_nan && count < width) || count == 0 { f64::NAN } else {
              match family {
                Moment::Sum => total,
                Moment::Mean => total / count as f64,
                Moment::Var | Moment::Std => {
                  if count < 2 { f64::NAN } else {
                    let variance = ((square - total * total / count as f64) / (count - 1) as f64).max(0.0);
                    if matches!(family, Moment::Std) { variance.sqrt() } else { variance }
                  }
                }
                Moment::Skew => {
                  if count < 3 { f64::NAN } else {
                    let n = count as f64;
                    let mean = total / n;
                    let m2 = (square - total * total / n).max(0.0);
                    let m3 = cube - 3.0 * mean * square + 2.0 * n * mean * mean * mean;
                    if m2 <= 0.0 { f64::NAN } else {
                      let population = (m3 / n) / (m2 / n).powf(1.5);
                      population * (n * (n - 1.0)).sqrt() / (n - 2.0)
                    }
                  }
                }
              }
            };
          }
        });
        return Ok(out.into_pyarray(py).unbind());
      }
    }
    if fixed && matches!(
      op, alpha_algo::SessionOp::Min | alpha_algo::SessionOp::Max
        | alpha_algo::SessionOp::Argmin | alpha_algo::SessionOp::Argmax
        | alpha_algo::SessionOp::ArgminRaw | alpha_algo::SessionOp::ArgmaxRaw
    ) {
      // Extrema family: chunk-independent monotonic deques.
      use std::collections::VecDeque;
      let is_max = matches!(op, alpha_algo::SessionOp::Max | alpha_algo::SessionOp::Argmax
        | alpha_algo::SessionOp::ArgmaxRaw);
      let is_arg = matches!(op, alpha_algo::SessionOp::Argmin | alpha_algo::SessionOp::Argmax
        | alpha_algo::SessionOp::ArgminRaw | alpha_algo::SessionOp::ArgmaxRaw);
      let raw = matches!(op, alpha_algo::SessionOp::ArgminRaw | alpha_algo::SessionOp::ArgmaxRaw);
      let n = values.len();
      {
        const CHUNK: usize = 65_536;
        let mut out = vec![f64::NAN; n];
        out.par_chunks_mut(CHUNK).enumerate().for_each(|(chunk_index, chunk)| {
          let chunk_start = chunk_index * CHUNK;
          let mut deque: VecDeque<usize> = VecDeque::new();
          let mut count = 0usize;
          for k in chunk_start.saturating_sub(window)..chunk_start {
            if !values[k].is_finite() { continue; }
            count += 1;
            while let Some(last) = deque.back().copied() {
              if (is_max && values[last] <= values[k]) || (!is_max && values[last] >= values[k]) {
                deque.pop_back();
              } else { break; }
            }
            deque.push_back(k);
          }
          for (offset, slot) in chunk.iter_mut().enumerate() {
            let index = chunk_start + offset;
            let start = index.saturating_sub(window - 1);
            while deque.front().is_some_and(|i| *i < start) { deque.pop_front(); }
            if index >= window && values[index - window].is_finite() { count -= 1; }
            if values[index].is_finite() {
              count += 1;
              while let Some(last) = deque.back().copied() {
                if (is_max && values[last] <= values[index]) || (!is_max && values[last] >= values[index]) {
                  deque.pop_back();
                } else { break; }
              }
              deque.push_back(index);
            }
            let width = (index + 1).min(window);
            if count < min_periods || (propagate_nan && count < width) { continue; }
            let Some(best) = deque.front().copied() else { continue };
            *slot = if !is_arg {
              values[best]
            } else {
              let distance = (index - best) as f64;
              if raw { distance } else if count <= 1 { 0.0 } else { distance / (count - 1) as f64 }
            };
          }
        });
        return Ok(out.into_pyarray(py).unbind());
      }
    }
    if matches!(
      op, alpha_algo::SessionOp::Sum | alpha_algo::SessionOp::Mean
        | alpha_algo::SessionOp::Var | alpha_algo::SessionOp::Std
        | alpha_algo::SessionOp::Skew
    ) {
      // Arbitrary intervals: prefix moments, still O(1) per output.
      let n = values.len();
      let mut count = vec![0u64; n + 1];
      let mut sum = vec![0.0f64; n + 1];
      let mut sumsq = vec![0.0f64; n + 1];
      let mut sum3 = vec![0.0f64; n + 1];
      for (i, value) in values.iter().copied().enumerate() {
        let finite = value.is_finite();
        count[i + 1] = count[i] + u64::from(finite);
        sum[i + 1] = sum[i] + if finite { value } else { 0.0 };
        sumsq[i + 1] = sumsq[i] + if finite { value * value } else { 0.0 };
        sum3[i + 1] = sum3[i] + if finite { value * value * value } else { 0.0 };
      }
      let mean = matches!(op, alpha_algo::SessionOp::Mean);
      let variance = matches!(op, alpha_algo::SessionOp::Var | alpha_algo::SessionOp::Std);
      let std = matches!(op, alpha_algo::SessionOp::Std);
      let skew = matches!(op, alpha_algo::SessionOp::Skew);
      let out: Vec<f64> = (0..n).into_par_iter().map(|index| {
        let start = starts[index] as usize;
        let end = (ends[index] as usize + 1).min(n);
        let m = count[end] - count[start];
        let width = end.saturating_sub(start);
        if m == 0 || m < min_periods as u64 || (propagate_nan && m < width as u64) { return f64::NAN; }
        let total = sum[end] - sum[start];
        if mean { return total / m as f64; }
        if variance {
          if m < 2 { return f64::NAN; }
          let square = sumsq[end] - sumsq[start];
          let var = ((square - total * total / m as f64) / (m - 1) as f64).max(0.0);
          return if std { var.sqrt() } else { var };
        }
        if skew {
          if m < 3 { return f64::NAN; }
          let m = m as f64;
          let mean = total / m;
          let square = sumsq[end] - sumsq[start];
          let cube = sum3[end] - sum3[start];
          let m2 = (square - total * total / m).max(0.0);
          let m3 = cube - 3.0 * mean * square + 2.0 * m * mean * mean * mean;
          if m2 <= 0.0 { return f64::NAN; }
          let population = (m3 / m) / (m2 / m).powf(1.5);
          return population * (m * (m - 1.0)).sqrt() / (m - 2.0);
        }
        total
      }).collect();
      return Ok(out.into_pyarray(py).unbind());
    }
    let mut state = alpha_algo::IntervalKernel::new(op)
      .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?
      .with_semantics(min_periods, propagate_nan);
    Ok(values.iter().copied().zip(starts.iter().copied()).zip(ends.iter().copied())
      .map(|((value, start), end)| state.update_explicit(start, end, value))
      .collect::<Vec<_>>().into_pyarray(py).unbind())
  }

  #[pyfunction]
  #[pyo3(signature = (x, y, starts, ends, correlation=false, window=None, min_periods=2, propagate_nan=false))]
  pub fn interval_rolling_pair(
    py: Python<'_>, x: PyReadonlyArray1<f64>, y: PyReadonlyArray1<f64>,
    starts: PyReadonlyArray1<u64>, ends: PyReadonlyArray1<u64>,
    correlation: bool, window: Option<usize>, min_periods: usize, propagate_nan: bool,
  ) -> PyResult<Py<PyArray1<f64>>> {
    let x = x.as_slice()?;
    let y = y.as_slice()?;
    let starts = starts.as_slice()?;
    let ends = ends.as_slice()?;
    if x.len() != y.len() || x.len() != starts.len() || x.len() != ends.len() {
      return Err(pyo3::exceptions::PyValueError::new_err(
        "interval_rolling_pair length mismatch"
      ));
    }
    let fixed = window.is_some();
    let window = window.unwrap_or(1).max(1);
    if fixed {
      // PairMoments family: chunk-independent sliding moments.
      let n = x.len();
      {
        const CHUNK: usize = 65_536;
        let mut out = vec![f64::NAN; n];
        out.par_chunks_mut(CHUNK).enumerate().for_each(|(chunk_index, chunk)| {
          let chunk_start = chunk_index * CHUNK;
          let (mut sx, mut sy) = (0.0f64, 0.0f64);
          let (mut sxx, mut syy, mut sxy) = (0.0f64, 0.0f64, 0.0f64);
          let mut count = 0usize;
          for k in chunk_start.saturating_sub(window)..chunk_start {
            if x[k].is_finite() && y[k].is_finite() {
              sx += x[k]; sy += y[k]; sxx += x[k] * x[k];
              syy += y[k] * y[k]; sxy += x[k] * y[k]; count += 1;
            }
          }
          for (offset, slot) in chunk.iter_mut().enumerate() {
            let index = chunk_start + offset;
            if x[index].is_finite() && y[index].is_finite() {
              sx += x[index]; sy += y[index]; sxx += x[index] * x[index];
              syy += y[index] * y[index]; sxy += x[index] * y[index]; count += 1;
            }
            if index >= window {
              let k = index - window;
              if x[k].is_finite() && y[k].is_finite() {
                sx -= x[k]; sy -= y[k]; sxx -= x[k] * x[k];
                syy -= y[k] * y[k]; sxy -= x[k] * y[k]; count -= 1;
              }
            }
            let width = (index + 1).min(window);
            if count < 2 || count < min_periods || (propagate_nan && count < width) {
              *slot = f64::NAN; continue;
            }
            let m = count as f64;
            let covariance = (sxy - sx * sy / m) / (m - 1.0);
            *slot = if !correlation {
              covariance
            } else {
              let vx = (sxx - sx * sx / m).max(0.0);
              let vy = (syy - sy * sy / m).max(0.0);
              let denom = (vx * vy).sqrt();
              if denom > 0.0 { (sxy - sx * sy / m) / denom } else { f64::NAN }
            };
          }
        });
        return Ok(out.into_pyarray(py).unbind());
      }
    }
    let mut state = alpha_algo::PairIntervalState::new(correlation);
    let _ = (min_periods, propagate_nan);
    Ok(x.iter().copied().zip(y.iter().copied())
      .zip(starts.iter().copied()).zip(ends.iter().copied())
      .map(|(((x, y), start), end)| state.update(start, end, x, y))
      .collect::<Vec<_>>().into_pyarray(py).unbind())
  }

  #[pyfunction]
  pub fn session_rolling_sum(
    values: Vec<f64>, session_ids: Vec<u32>, lookback_sessions: usize,
  ) -> PyResult<Vec<f64>> {
    let ctx = Context::default();
    ta_session_rolling_sum(&ctx, &values, &session_ids, lookback_sessions)
      .map_err(|e| e.into())
  }

  #[pyfunction]
  pub fn session_rolling_mean(
    values: Vec<f64>, session_ids: Vec<u32>, lookback_sessions: usize,
  ) -> PyResult<Vec<f64>> {
    let ctx = Context::default();
    ta_session_rolling_mean(&ctx, &values, &session_ids, lookback_sessions)
      .map_err(|e| e.into())
  }

  #[pyfunction]
  #[pyo3(signature = (/, start=None, end=None, groups=None, flags=None))]
  pub fn set_ctx<'py>(
    _py: Python<'py>,
    start: Option<i32>,
    end: Option<i32>,
    groups: Option<u32>,
    flags: Option<u64>,
  ) -> PyResult<()> {
    match _ALGO_CTX_.try_write() {
      Ok(mut ctx) => {
        start.map(|s| ctx._start = s);
        end.map(|e| ctx._end = e);
        groups.map(|g| ctx._groups = g);
        flags.map(|f| ctx._flags = f);
        Ok(())
      }
      Err(_e) => Err(PyValueError::new_err("failed to set context")),
    }
  }

  /// Exponential Moving Average (variant of EMA)
  ///
  /// alpha = 2 / (n + 1)
  ///
  /// https://en.wikipedia.org/wiki/Moving_average#Exponential_moving_average
  ///
  #[pyfunction]
  pub fn ema<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    let mut ctx = ctx(py);

    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;

      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ema(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;

      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_ema(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays

      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;

      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }

      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();

        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let out = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((out, input)) = out.zip(input) {
              ta_ema(&ctx, out, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);

        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();

        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let out = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((out, input)) = out.zip(input) {
              ta_ema(&ctx, out, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);

        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        // NumT array can only be f64 or f32
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      // NumT array can only be f64 or f32
      Err(PyValueError::new_err("invalid input"))
    }
  }

  include!("./algo_bindings.rs");
}

#[pyclass(unsendable)]
pub struct LotBook {
  method: i32,
  lots: Vec<(f64, f64, f64, i32)>,
}

#[pymethods]
impl LotBook {
  #[new]
  fn new(method: i32) -> Self { Self { method, lots: Vec::new() } }

  fn apply_fill(&mut self, quantity: f64, price: f64, multiplier: f64, is_today: i32, offset: i32) -> f64 {
    let prior: f64 = self.lots.iter().map(|lot| lot.0).sum();
    if prior == 0.0 || (prior > 0.0) == (quantity > 0.0) {
      self.lots.push((quantity, price, multiplier, is_today));
      return 0.0;
    }
    let close_abs = prior.abs().min(quantity.abs());
    let mut remaining = close_abs;
    let mut realized = 0.0;
    let mut order: Vec<usize> = (0..self.lots.len()).collect();
    if self.method == 1 {
      order.reverse();
    } else if self.method == 2 {
      order.sort_by(|&left, &right| self.lots[right].1.partial_cmp(&self.lots[left].1).unwrap_or(std::cmp::Ordering::Equal));
    }
    for index in order {
      if remaining <= 1e-12 { break; }
      let today = self.lots[index].3;
      if (offset == 1 && today != 1) || (offset == 2 && today != 0) { continue; }
      let take = remaining.min(self.lots[index].0.abs());
      realized += take * (price - self.lots[index].1) * self.lots[index].2;
      self.lots[index].0 -= if self.lots[index].0 > 0.0 { take } else { -take };
      remaining -= take;
    }
    self.lots.retain(|lot| lot.0.abs() > 1e-12);
    let flip = quantity.abs() - close_abs;
    if flip > 1e-12 {
      self.lots.push((if quantity > 0.0 { flip } else { -flip }, price, multiplier, is_today));
    }
    if prior > 0.0 { realized } else { -realized }
  }

  fn quantity(&self) -> f64 { self.lots.iter().map(|lot| lot.0).sum() }

  fn lots_snapshot(&self) -> Vec<(f64, f64, f64, i32)> { self.lots.clone() }
}

#[pyclass(unsendable)]
pub struct LedgerState {
  accounts: std::collections::HashMap<String, LedgerAccount>,
  margins: std::collections::HashMap<String, MarginAccount>,
  cost_methods: std::collections::HashMap<String, i32>,
  lots: std::collections::HashMap<String, std::collections::HashMap<String, LotBook>>,
}

#[pymethods]
impl LedgerState {
  #[new]
  fn new() -> Self {
    Self {
      accounts: std::collections::HashMap::new(),
      margins: std::collections::HashMap::new(),
      cost_methods: std::collections::HashMap::new(),
      lots: std::collections::HashMap::new(),
    }
  }

  fn ensure(&mut self, ledger_id: &str, cash: f64) {
    self.accounts.entry(ledger_id.to_string()).or_insert_with(|| LedgerAccount::new(cash));
  }

  fn set_cash(&mut self, ledger_id: &str, cash: f64) {
    let account = self.accounts.entry(ledger_id.to_string()).or_insert_with(|| LedgerAccount::new(cash));
    account.cash = cash;
  }

  fn set_position(&mut self, ledger_id: &str, product: &str, quantity: f64, cost: f64) {
    let account = self.accounts.entry(ledger_id.to_string()).or_insert_with(|| LedgerAccount::new(0.0));
    account.positions.insert(product.to_string(), (quantity, cost));
  }

  fn apply_fill(
    &mut self, ledger_id: &str, product: &str,
    quantity: f64, price: f64, multiplier: f64, fee: f64,
    margin_ratio: f64, margin_accounting: bool,
  ) -> f64 {
    let account = self.accounts.get_mut(ledger_id);
    let Some(account) = account else { return 0.0 };
    let realized = account.apply_fill(product, quantity, price, multiplier, fee);
    // Fully-funded cash accounting settles notional, not realized PnL.
    account.cash -= realized;
    if !margin_accounting {
      account.cash -= quantity * price * multiplier;
    }
    if margin_accounting {
      let margin = self.margins.entry(ledger_id.to_string()).or_insert_with(MarginAccount::new);
      let (position, _) = account.position(product);
      margin.update(product, position, price, multiplier, margin_ratio);
    }
    realized
  }

  fn apply_fills_batch(
    &mut self, ledger_id: &str, products: Vec<String>,
    quantities: Vec<f64>, prices: Vec<f64>, multipliers: Vec<f64>,
    fees: Vec<f64>, margin_ratios: Vec<f64>, margin_accounting: bool,
  ) -> PyResult<Vec<(f64, f64, f64)>> {
    let length = products.len();
    if quantities.len() != length || prices.len() != length
      || multipliers.len() != length || fees.len() != length
      || margin_ratios.len() != length
    {
      return Err(pyo3::exceptions::PyValueError::new_err("fill batch length mismatch"));
    }
    let mut result = Vec::with_capacity(length);
    for index in 0..length {
      let Some(account) = self.accounts.get_mut(ledger_id) else {
        result.push((0.0, 0.0, 0.0));
        continue;
      };
      let realized = account.apply_fill(
        &products[index], quantities[index], prices[index],
        multipliers[index], fees[index],
      );
      account.cash -= realized;
      if !margin_accounting {
        account.cash -= quantities[index] * prices[index] * multipliers[index];
      }
      let (position, _) = account.position(&products[index]);
      let cash = account.cash;
      if margin_accounting {
        let margin = self.margins.entry(ledger_id.to_string()).or_insert_with(MarginAccount::new);
        margin.update(&products[index], position, prices[index], multipliers[index], margin_ratios[index]);
      }
      result.push((realized, cash, position));
    }
    Ok(result)
  }

  fn apply_lot_position(
    &mut self, ledger_id: &str, product: &str, method: i32,
    quantity: f64, price: f64, multiplier: f64, is_today: i32, offset: i32,
  ) -> (f64, f64) {
    let method = if method > 0 { method } else { *self.cost_methods.get(ledger_id).unwrap_or(&0) };
    if !self.lots.contains_key(ledger_id) {
      self.lots.insert(ledger_id.to_string(), std::collections::HashMap::new());
    }
    let book = self.lots.get_mut(ledger_id).unwrap()
      .entry(product.to_string()).or_insert_with(|| LotBook::new(method));
    let realized = book.apply_fill(quantity, price, multiplier, is_today, offset);
    let quantity_after = book.quantity();
    if let Some(account) = self.accounts.get_mut(ledger_id) {
      let prior_cost = account.positions.get(product).map(|entry| entry.1).unwrap_or(0.0);
      account.positions.insert(product.to_string(), (quantity_after, prior_cost));
    }
    (realized, quantity_after)
  }

  fn settle_margin_fill(
    &mut self, ledger_id: &str, product: &str, basis_price: f64, ratio: f64,
    fee: f64, realized: f64, quantity_after: f64, multiplier: f64,
  ) -> f64 {
    let Some(account) = self.accounts.get_mut(ledger_id) else { return 0.0 };
    let margin = self.margins.entry(ledger_id.to_string()).or_insert_with(MarginAccount::new);
    let prior_margin = margin.product_margin(product);
    let after_margin = margin.update(product, quantity_after, basis_price, multiplier, ratio);
    account.cash += realized - fee - (after_margin - prior_margin);
    after_margin
  }

  fn apply_margin_fill(
    &mut self, ledger_id: &str, product: &str,
    quantity: f64, price: f64, multiplier: f64, fee: f64,
    basis_price: f64, ratio: f64,
  ) -> f64 {
    let Some(account) = self.accounts.get_mut(ledger_id) else { return 0.0 };
    let (prior_quantity, prior_cost) = account.position(product);
    let new_quantity = prior_quantity + quantity;
    let epsilon = 1e-12;
    let mut realized = 0.0;
    let mut new_cost = prior_cost;
    if prior_quantity == 0.0 || (prior_quantity > 0.0) == (quantity > 0.0) {
      new_cost = if new_quantity.abs() <= epsilon {
        0.0
      } else {
        (prior_quantity * prior_cost + quantity * price) / new_quantity
      };
    } else {
      let close_abs = prior_quantity.abs().min(quantity.abs());
      realized = close_abs * (price - prior_cost) * prior_quantity.signum() * multiplier;
      if new_quantity.abs() <= epsilon {
        new_cost = 0.0;
      } else if quantity.abs() > prior_quantity.abs() {
        new_cost = price;
      }
    }
    let quantity_after = if new_quantity.abs() <= epsilon { 0.0 } else { new_quantity };
    account.positions.insert(product.to_string(), (quantity_after, new_cost));
    let margin = self.margins.entry(ledger_id.to_string()).or_insert_with(MarginAccount::new);
    let prior_margin = margin.product_margin(product);
    let after_margin = margin.update(product, quantity_after, basis_price, multiplier, ratio);
    account.cash += realized - fee - (after_margin - prior_margin);
    realized
  }

  fn set_cost_method(&mut self, ledger_id: &str, method: i32) {
    self.cost_methods.insert(ledger_id.to_string(), method);
  }

  fn apply_lot_fill(
    &mut self, ledger_id: &str, product: &str, method: i32,
    quantity: f64, price: f64, multiplier: f64, fee: f64,
    is_today: i32, offset: i32,
  ) -> f64 {
    let method = if method > 0 { method } else { *self.cost_methods.get(ledger_id).unwrap_or(&0) };
    if !self.lots.contains_key(ledger_id) {
      self.lots.insert(ledger_id.to_string(), std::collections::HashMap::new());
    }
    let books = self.lots.get_mut(ledger_id).unwrap();
    let book = books.entry(product.to_string()).or_insert_with(|| LotBook::new(method));
    let realized = book.apply_fill(quantity, price, multiplier, is_today, offset);
    let quantity_after = book.quantity();
    if let Some(account) = self.accounts.get_mut(ledger_id) {
      let prior_cost = account.positions.get(product).map(|entry| entry.1).unwrap_or(0.0);
      account.positions.insert(product.to_string(), (quantity_after, prior_cost));
      account.cash -= fee;
      account.cash -= quantity * price * multiplier;
    }
    realized
  }

  fn set_lots(&mut self, ledger_id: &str, product: &str, method: i32, lots: Vec<(f64, f64, f64, i32)>) {
    if !self.lots.contains_key(ledger_id) {
      self.lots.insert(ledger_id.to_string(), std::collections::HashMap::new());
    }
    let book = self.lots.get_mut(ledger_id).unwrap()
      .entry(product.to_string()).or_insert_with(|| LotBook::new(method));
    book.lots = lots;
  }

  fn lots(&self, ledger_id: &str, product: &str) -> Vec<(f64, f64, f64, i32)> {
    self.lots.get(ledger_id)
      .and_then(|books| books.get(product))
      .map(|book| book.lots_snapshot())
      .unwrap_or_default()
  }

  fn cash(&self, ledger_id: &str) -> f64 {
    self.accounts.get(ledger_id).map(|account| account.cash).unwrap_or(0.0)
  }

  fn position(&self, ledger_id: &str, product: &str) -> (f64, f64) {
    self.accounts.get(ledger_id).map(|account| account.position(product)).unwrap_or((0.0, 0.0))
  }

  fn product_margin(&self, ledger_id: &str, product: &str) -> f64 {
    self.margins.get(ledger_id).map(|account| account.product_margin(product)).unwrap_or(0.0)
  }

  fn reserved(&self, ledger_id: &str) -> f64 {
    self.margins.get(ledger_id).map(|account| account.reserved).unwrap_or(0.0)
  }
}

#[pyclass(unsendable)]
pub struct MarginAccount {
  reserved: f64,
  by_product: std::collections::HashMap<String, f64>,
}

#[pymethods]
impl MarginAccount {
  #[new]
  fn new() -> Self { Self { reserved: 0.0, by_product: std::collections::HashMap::new() } }

  fn update(&mut self, product: &str, quantity: f64, price: f64, multiplier: f64, ratio: f64) -> f64 {
    let margin = quantity.abs() * price * multiplier * ratio;
    let previous = self.by_product.insert(product.to_string(), margin).unwrap_or(0.0);
    self.reserved += margin - previous;
    margin
  }

  #[getter]
  fn reserved(&self) -> f64 { self.reserved }

  fn product_margin(&self, product: &str) -> f64 {
    self.by_product.get(product).copied().unwrap_or(0.0)
  }
}

#[derive(Clone, PartialEq, Eq, PartialOrd, Ord)]
enum TracePlanKind {
  Normal(usize, usize),
  Pending(usize),
  Constraint(usize),
  Rounding,
}

struct TraceEntry {
  base: Py<pyo3::types::PyDict>,
  order_id: u64,
  column: usize,
  delta: f64,
  fee: f64,
  signal_text: String,
  execution_text: String,
  product: String,
  order_text: String,
}

#[pyclass(unsendable)]
pub struct NativeTraceBuilder;

#[pymethods]
impl NativeTraceBuilder {
  #[new]
  fn new() -> Self { Self }

  fn build(
    &self, py: Python<'_>, alias: &str,
    orders: Vec<(u64, usize, f64, f64, i32)>,
    audits: Vec<(usize, u64, f64, f64, f64)>,
    timestamps: Vec<String>, execution_timestamps: Vec<String>,
    products: Vec<String>, initial_cash: f64, base_currency: &str,
    custom: bool, intents: Vec<(u64, f64)>,
    execution_delay: usize,
    pending: Vec<(u64, usize, f64)>,
    constraints: Vec<(usize, u64, usize, f64, f64, f64, f64, f64)>,
  ) -> PyResult<Vec<Py<pyo3::types::PyDict>>> {
    let mut audit_by_order = std::collections::HashMap::new();
    let mut audit_rows = std::collections::BTreeSet::new();
    for (row, order_id, _delta, price, _fee) in audits {
      audit_by_order.insert(order_id, (row, price));
      audit_rows.insert(row);
    }
    let mut positions: std::collections::HashMap<usize, f64> = std::collections::HashMap::new();
    let mut cash = initial_cash;
    let mut order_info: std::collections::HashMap<u64, (f64, f64, &'static str, f64, f64, String, String)> = std::collections::HashMap::new();
    for (order_id, column, delta, fee, _status) in &orders {
      let (execution_row, price) = audit_by_order.get(order_id).copied().unwrap_or((1, 0.0));
      let execution_row = execution_row.min(timestamps.len().saturating_sub(1));
      let signal_row = execution_row.saturating_sub(1);
      let signal_text = timestamps.get(signal_row).cloned().unwrap_or_default();
      let prior = positions.get(column).copied().unwrap_or(0.0);
      let leg = if prior * *delta < 0.0 { "close" } else { "open" };
      let cash_before = cash;
      cash -= *delta * price + *fee;
      positions.insert(*column, prior + *delta);
      let group = format!("{alias}-{signal_text}-group-{order_id}");
      order_info.insert(*order_id, (
        price, *fee, leg, cash_before, cash,
        group.clone(), format!("{group}:intent"),
      ));
    }
    let mut templates: Vec<Py<pyo3::types::PyDict>> = Vec::with_capacity(6);
    for step in 0..6 {
      let (step_name, label) = match step {
        0 => ("construct_order", "构造原子订单"),
        1 => ("resolve_execution_price", "解析成交价"),
        2 => ("slippage", "计算滑点价格"),
        3 => ("fee", "计算手续费"),
        4 => ("ledger_update", "成交落账"),
        _ => ("order_terminal", "订单成交"),
      };
      let template = pyo3::types::PyDict::new(py);
      template.set_item(pyo3::intern!(py, "order_group_id"), "")?;
      template.set_item(pyo3::intern!(py, "parent_intent_id"), "")?;
      template.set_item(pyo3::intern!(py, "step"), step_name)?;
      template.set_item(pyo3::intern!(py, "label"), label)?;
      template.set_item(pyo3::intern!(py, "leg_role"), "atomic_net")?;
      template.set_item(pyo3::intern!(py, "offset"), "open")?;
      template.set_item(pyo3::intern!(py, "revision"), 0)?;
      template.set_item(pyo3::intern!(py, "effective_price"), py.None())?;
      template.set_item(pyo3::intern!(py, "reject_reason"), py.None())?;
      templates.push(template.unbind());
    }
    let fee_detail_template = pyo3::types::PyDict::new(py);
    fee_detail_template.set_item(pyo3::intern!(py, "mode"), "zero")?;
    fee_detail_template.set_item(pyo3::intern!(py, "fixed_rate"), 0.0)?;
    let fee_detail_template = fee_detail_template.unbind();
    let empty_detail_template = pyo3::types::PyDict::new(py);
    let empty_detail_template = empty_detail_template.unbind();
    let construct_detail_template = pyo3::types::PyDict::new(py);
    construct_detail_template.set_item(pyo3::intern!(py, "group_policy"), "sequential_close_then_open")?;
    construct_detail_template.set_item(pyo3::intern!(py, "paired_execution_policy"), py.None())?;
    let resolve_detail_template = pyo3::types::PyDict::new(py);
    resolve_detail_template.set_item(pyo3::intern!(py, "basis"), "open")?;
    let slippage_detail_template = pyo3::types::PyDict::new(py);
    slippage_detail_template.set_item(pyo3::intern!(py, "mode"), "none")?;
    slippage_detail_template.set_item(pyo3::intern!(py, "slippage_bps"), 0.0)?;
    let ledger_id_text = format!("private:{alias}");
    let mut entries = Vec::with_capacity(orders.len());
    for (order_id, column, delta, fee, _status) in &orders {
      let (execution_row, _price) = audit_by_order.get(order_id).copied().unwrap_or((1, 0.0));
      let execution_row = execution_row.min(timestamps.len().saturating_sub(1));
      let signal_row = execution_row.saturating_sub(1 + execution_delay);
      let signal_text = timestamps.get(signal_row).cloned().unwrap_or_default();
      let execution_text = if execution_delay > 0 {
        timestamps.get(execution_row).cloned().unwrap_or_default()
      } else {
        execution_timestamps.get(signal_row).cloned().unwrap_or_default()
      };
      let product = products.get(*column).cloned().unwrap_or_default();
      let order_text = format!("{alias}-{signal_text}-{order_id}");
      let info = &order_info[order_id];
      let base = pyo3::types::PyDict::new(py);
      base.set_item(pyo3::intern!(py, "order_id"), &order_text)?;
      base.set_item(pyo3::intern!(py, "order_group_id"), &info.5)?;
      base.set_item(pyo3::intern!(py, "parent_intent_id"), &info.6)?;
      base.set_item(pyo3::intern!(py, "strategy_id"), alias)?;
      base.set_item(pyo3::intern!(py, "product"), &product)?;
      base.set_item(pyo3::intern!(py, "leg_role"), info.2)?;
      base.set_item(pyo3::intern!(py, "offset"), if info.2 == "close" { "close" } else { "open" })?;
      base.set_item(pyo3::intern!(py, "revision"), 0)?;
      base.set_item(pyo3::intern!(py, "reject_reason"), py.None())?;
      entries.push(TraceEntry {
        base: base.unbind(),
        order_id: *order_id, column: *column, delta: *delta, fee: *fee,
        signal_text, execution_text, product, order_text,
      });
    }
    let intent_by_order: std::collections::HashMap<u64, f64> = intents.into_iter().collect();
    let mut plan: Vec<(String, i32, i64, usize, TracePlanKind)> = Vec::with_capacity(entries.len() * 6);
    let mut sequence = 0usize;
    for (index, entry) in entries.iter().enumerate() {
      for step in 0..6 {
        let (timestamp, rank, key) = match step {
          0 => (entry.signal_text.clone(), 0, entry.order_id as i64),
          1 => (entry.execution_text.clone(), 1, entry.order_id as i64),
          2 => (entry.execution_text.clone(), 2, entry.order_id as i64),
          3 => (entry.execution_text.clone(), 3, entry.order_id as i64),
          4 => (entry.execution_text.clone(), 5, sequence as i64),
          _ => (entry.execution_text.clone(), 6, entry.order_id as i64),
        };
        plan.push((timestamp, rank, key, sequence, TracePlanKind::Normal(index, step)));
        sequence += 1;
      }
    }
    for (index, (order_id, column, delta)) in pending.iter().enumerate() {
      let timestamp = timestamps.last().cloned().unwrap_or_default();
      plan.push((timestamp, 0, *order_id as i64, sequence, TracePlanKind::Pending(index)));
      let _ = (column, delta);
      sequence += 1;
    }
    for (index, constraint) in constraints.iter().enumerate() {
      let (row, order_id, _column, _before, _after, _scale, _available, _required) = constraint;
      let signal_row = row.saturating_sub(1).min(execution_timestamps.len().saturating_sub(1));
      let timestamp = execution_timestamps.get(signal_row).cloned().unwrap_or_default();
      plan.push((timestamp, 4, *order_id as i64, sequence, TracePlanKind::Constraint(index)));
      sequence += 1;
    }
    if custom {
      for row in &audit_rows {
        if *row < timestamps.len() {
          plan.push((timestamps[*row].clone(), -1, -1, sequence, TracePlanKind::Rounding));
          sequence += 1;
        }
      }
    }
    plan.sort();
    let mut rows = Vec::with_capacity(plan.len());
    for (_timestamp, _rank, _key, seq, plan_kind) in plan {
      if let TracePlanKind::Pending(index) = plan_kind {
        let (pending_id, column, delta) = pending[index];
        let signal_text = timestamps.last().cloned().unwrap_or_default();
        let product = products.get(column).cloned().unwrap_or_default();
        let position = positions.get(&column).copied().unwrap_or(0.0);
        let leg = if position * delta < 0.0 { "close" } else { "open" };
        let order_text = format!("{alias}-{signal_text}-{pending_id}");
        let group_id = format!("{alias}-{signal_text}-group-{pending_id}");
        let dict = templates[0].bind(py).copy()?;
        dict.set_item(pyo3::intern!(py, "order_id"), &order_text)?;
        dict.set_item(pyo3::intern!(py, "order_group_id"), &group_id)?;
        dict.set_item(pyo3::intern!(py, "parent_intent_id"), format!("{group_id}:intent"))?;
        dict.set_item(pyo3::intern!(py, "strategy_id"), alias)?;
        dict.set_item(pyo3::intern!(py, "timestamp"), &signal_text)?;
        dict.set_item(pyo3::intern!(py, "product"), product)?;
        dict.set_item(pyo3::intern!(py, "quantity"), delta)?;
        dict.set_item(pyo3::intern!(py, "intent_quantity"), delta)?;
        dict.set_item(pyo3::intern!(py, "requested_quantity"), delta.abs())?;
        dict.set_item(pyo3::intern!(py, "filled_quantity"), 0.0)?;
        dict.set_item(pyo3::intern!(py, "remaining_quantity"), delta.abs())?;
        dict.set_item(pyo3::intern!(py, "unfilled_quantity"), delta.abs())?;
        dict.set_item(pyo3::intern!(py, "status"), "draft")?;
        dict.set_item(pyo3::intern!(py, "leg_role"), leg)?;
        dict.set_item(pyo3::intern!(py, "offset"), if leg == "close" { "close" } else { "open" })?;
        dict.set_item(pyo3::intern!(py, "execution_effect"), "mixed")?;
        dict.set_item(pyo3::intern!(py, "effective_price"), py.None())?;
        dict.set_item(pyo3::intern!(py, "fee_cost"), py.None())?;
        let detail = pyo3::types::PyDict::new(py);
        detail.set_item(pyo3::intern!(py, "group_policy"), "sequential_close_then_open")?;
        detail.set_item(pyo3::intern!(py, "child_order_ids"), pyo3::types::PyTuple::new(py, [order_text.as_str()])?)?;
        detail.set_item(pyo3::intern!(py, "paired_execution_policy"), py.None())?;
        dict.set_item(pyo3::intern!(py, "details"), detail)?;
        rows.push(dict.unbind());
        continue;
      }
      if let TracePlanKind::Rounding = plan_kind {
        let dict = pyo3::types::PyDict::new(py);
        dict.set_item(pyo3::intern!(py, "order_id"), "")?;
        dict.set_item(pyo3::intern!(py, "order_group_id"), "")?;
        dict.set_item(pyo3::intern!(py, "parent_intent_id"), "")?;
        dict.set_item(pyo3::intern!(py, "strategy_id"), alias)?;
        dict.set_item(pyo3::intern!(py, "timestamp"), _timestamp)?;
        dict.set_item(pyo3::intern!(py, "step"), "quantity_rounding")?;
        dict.set_item(pyo3::intern!(py, "label"), "按最小买入手数取整")?;
        dict.set_item(pyo3::intern!(py, "product"), py.None())?;
        dict.set_item(pyo3::intern!(py, "quantity"), py.None())?;
        dict.set_item(pyo3::intern!(py, "intent_quantity"), py.None())?;
        dict.set_item(pyo3::intern!(py, "requested_quantity"), py.None())?;
        dict.set_item(pyo3::intern!(py, "filled_quantity"), 0.0)?;
        dict.set_item(pyo3::intern!(py, "remaining_quantity"), py.None())?;
        dict.set_item(pyo3::intern!(py, "unfilled_quantity"), py.None())?;
        dict.set_item(pyo3::intern!(py, "status"), "draft")?;
        dict.set_item(pyo3::intern!(py, "leg_role"), "")?;
        dict.set_item(pyo3::intern!(py, "offset"), "")?;
        dict.set_item(pyo3::intern!(py, "execution_effect"), "mixed")?;
        dict.set_item(pyo3::intern!(py, "revision"), 0)?;
        dict.set_item(pyo3::intern!(py, "effective_price"), py.None())?;
        dict.set_item(pyo3::intern!(py, "fee_cost"), py.None())?;
        dict.set_item(pyo3::intern!(py, "reject_reason"), py.None())?;
        dict.set_item(pyo3::intern!(py, "details"), pyo3::types::PyDict::new(py))?;
        rows.push(dict.unbind());
        continue;
      }
      if let TracePlanKind::Constraint(index) = plan_kind {
        let (row, order_id, column, before, after, scale, available, required) = constraints[index];
        let signal_row = row.saturating_sub(1 + execution_delay).min(execution_timestamps.len().saturating_sub(1));
        let signal_text = timestamps.get(signal_row).cloned().unwrap_or_default();
        let timestamp = execution_timestamps.get(signal_row).cloned().unwrap_or_default();
        let product = products.get(column).cloned().unwrap_or_default();
        let order_text = format!("{alias}-{signal_text}-{order_id}");
        let group_id = format!("{alias}-{signal_text}-group-{order_id}");
        let (price, _fee, _leg, _cash_before, _cash_after, _g, _p) = &order_info[&order_id];
        let dict = pyo3::types::PyDict::new(py);
        dict.set_item(pyo3::intern!(py, "order_id"), &order_text)?;
        dict.set_item(pyo3::intern!(py, "order_group_id"), &group_id)?;
        dict.set_item(pyo3::intern!(py, "parent_intent_id"), format!("{group_id}:intent"))?;
        dict.set_item(pyo3::intern!(py, "strategy_id"), alias)?;
        dict.set_item(pyo3::intern!(py, "timestamp"), timestamp)?;
        dict.set_item(pyo3::intern!(py, "step"), "execution_cash_constraint")?;
        dict.set_item(pyo3::intern!(py, "label"), "成交增量保证金约束")?;
        dict.set_item(pyo3::intern!(py, "product"), product)?;
        dict.set_item(pyo3::intern!(py, "quantity"), after)?;
        dict.set_item(pyo3::intern!(py, "intent_quantity"), before)?;
        dict.set_item(pyo3::intern!(py, "requested_quantity"), before)?;
        dict.set_item(pyo3::intern!(py, "filled_quantity"), 0.0)?;
        dict.set_item(pyo3::intern!(py, "remaining_quantity"), before)?;
        dict.set_item(pyo3::intern!(py, "unfilled_quantity"), before)?;
        dict.set_item(pyo3::intern!(py, "status"), "accepted")?;
        dict.set_item(pyo3::intern!(py, "leg_role"), "open")?;
        dict.set_item(pyo3::intern!(py, "offset"), "open")?;
        dict.set_item(pyo3::intern!(py, "execution_effect"), "increase")?;
        dict.set_item(pyo3::intern!(py, "revision"), 0)?;
        dict.set_item(pyo3::intern!(py, "effective_price"), price)?;
        dict.set_item(pyo3::intern!(py, "fee_cost"), 0.0)?;
        dict.set_item(pyo3::intern!(py, "reject_reason"), py.None())?;
        let detail = pyo3::types::PyDict::new(py);
        detail.set_item(pyo3::intern!(py, "before_quantity"), before)?;
        detail.set_item(pyo3::intern!(py, "after_quantity"), after)?;
        detail.set_item(pyo3::intern!(py, "scale"), scale)?;
        detail.set_item(pyo3::intern!(py, "available_cash"), available)?;
        detail.set_item(pyo3::intern!(py, "required_cash"), required)?;
        dict.set_item(pyo3::intern!(py, "details"), detail)?;
        rows.push(dict.unbind());
        continue;
      }
      let (entry_index, step) = match plan_kind {
        TracePlanKind::Normal(index, step) => (index, step),
        _ => unreachable!(),
      };
      let entry = &entries[entry_index];
      let order_id = entry.order_id;
      let delta = entry.delta;
      let fee = entry.fee;
      let info = &order_info[&order_id];
      let (price, fee_value, leg, cash_before, cash_after) =
        (info.0, info.1, info.2, info.3, info.4);
      let group_id = &info.5;
      let parent_id = &info.6;
      let filled_quantity_value = delta.abs();
      let intent_quantity = intent_by_order.get(&order_id).copied().map(f64::abs).unwrap_or(filled_quantity_value);
      let sign = if delta < 0.0 { -1.0 } else { 1.0 };
      let quantity = if step < 4 { intent_quantity } else { filled_quantity_value };
      let signed_quantity = if step < 4 { sign * intent_quantity } else { delta };
      let timestamp = if step == 0 { entry.signal_text.as_str() } else { entry.execution_text.as_str() };
      let (status, filled, remaining) = match step {
        0 => ("draft", 0.0, quantity),
        1 | 2 | 3 => ("accepted", 0.0, quantity),
        _ => ("filled", filled_quantity_value, 0.0),
      };
      let dict = entry.base.bind(py).copy()?;
      let (step_name, label) = match step {
        0 => ("construct_order", "构造原子订单"),
        1 => ("resolve_execution_price", "解析成交价"),
        2 => ("slippage", "计算滑点价格"),
        3 => ("fee", "计算手续费"),
        4 => ("ledger_update", "成交落账"),
        _ => ("order_terminal", "订单成交"),
      };
      dict.set_item(pyo3::intern!(py, "step"), step_name)?;
      dict.set_item(pyo3::intern!(py, "label"), label)?;
      dict.set_item(pyo3::intern!(py, "timestamp"), timestamp)?;
      dict.set_item(pyo3::intern!(py, "quantity"), signed_quantity)?;
      dict.set_item(pyo3::intern!(py, "intent_quantity"), signed_quantity)?;
      dict.set_item(pyo3::intern!(py, "requested_quantity"), quantity)?;
      dict.set_item(pyo3::intern!(py, "filled_quantity"), filled)?;
      dict.set_item(pyo3::intern!(py, "remaining_quantity"), remaining)?;
      dict.set_item(pyo3::intern!(py, "unfilled_quantity"), remaining)?;
      dict.set_item(pyo3::intern!(py, "status"), status)?;
      dict.set_item(
        "execution_effect",
        if step < 2 { "mixed" } else if delta > 0.0 { "increase" } else { "reduce" },
      )?;
      if step == 0 { dict.set_item(pyo3::intern!(py, "effective_price"), py.None())?; }
      else { dict.set_item(pyo3::intern!(py, "effective_price"), price)?; }
      if step < 3 { dict.set_item(pyo3::intern!(py, "fee_cost"), py.None())?; }
      else { dict.set_item(pyo3::intern!(py, "fee_cost"), fee)?; }
      let detail_dict = match step {
        0 => construct_detail_template.copy()?.unbind(),
        1 => resolve_detail_template.copy()?.unbind(),
        2 => slippage_detail_template.copy()?.unbind(),
        3 => fee_detail_template.clone_ref(py),
        5 => empty_detail_template.clone_ref(py),
        _ => pyo3::types::PyDict::new(py).unbind(),
      };
      match step {
        0 => {
          let detail = detail_dict.bind(py);
          let children = pyo3::types::PyTuple::new(py, [entry.order_text.as_str()])?;
          detail.set_item(pyo3::intern!(py, "child_order_ids"), children)?;
        }
        1 => { detail_dict.bind(py).set_item(pyo3::intern!(py, "price"), price)?; }
        2 => { detail_dict.bind(py).set_item(pyo3::intern!(py, "base_price"), price)?; }
        3 => {}
        4 => {
          let detail = detail_dict.bind(py);
          detail.set_item(pyo3::intern!(py, "fill_id"), format!("{}:fill:1", entry.order_text))?;
          detail.set_item(pyo3::intern!(py, "ledger_id"), &ledger_id_text)?;
          detail.set_item(pyo3::intern!(py, "cash_pool_id"), &ledger_id_text)?;
          detail.set_item(pyo3::intern!(py, "account_currency"), base_currency)?;
          detail.set_item(pyo3::intern!(py, "cash_pool_base_currency"), base_currency)?;
          detail.set_item(pyo3::intern!(py, "price"), price)?;
          detail.set_item(pyo3::intern!(py, "fee_cost"), fee)?;
          detail.set_item(pyo3::intern!(py, "cash_before"), cash_before)?;
          detail.set_item(pyo3::intern!(py, "cash_after"), cash_after)?;
          detail.set_item(pyo3::intern!(py, "margin_before"), 0.0)?;
          detail.set_item(pyo3::intern!(py, "margin_after"), 0.0)?;
        }
        _ => {}
      }
      let _ = (fee_value, seq);
      dict.set_item(pyo3::intern!(py, "details"), detail_dict)?;
      rows.push(dict.unbind());
    }
    Ok(rows)
  }
}

fn fast_sum<I: IntoIterator<Item = f64>>(values: I) -> f64 {
  let mut sum = 0.0f64; let mut compensation = 0.0f64;
  for value in values {
    let next = sum + value;
    if sum.abs() >= value.abs() { compensation += (sum - next) + value; }
    else { compensation += (value - next) + sum; }
    sum = next;
  }
  sum + compensation
}

fn update_native_lots(lots: &mut Vec<(f64, f64)>, delta: f64, price: f64, method: i32) -> f64 {
  if delta.abs() <= 1e-15 { return 0.0; }
  let mut remaining = delta;
  let mut realized = 0.0;
  while remaining.abs() > 1e-12 {
    let Some(prior) = lots.first().map(|lot| lot.0) else { break; };
    if prior * remaining > 0.0 { break; }
    let position = lots.iter().map(|lot| lot.0).sum::<f64>();
    if position.abs() <= 1e-15 { break; }
    let select = if method == 1 {
      lots.len() - 1
    } else if method == 2 {
      lots.iter().enumerate().max_by(|a, b| a.1.1.partial_cmp(&b.1.1).unwrap()).map(|x| x.0).unwrap_or(0)
    } else { 0 };
    let (lot_qty, lot_price) = lots[select];
    let close = remaining.abs().min(lot_qty.abs()) * lot_qty.signum();
    realized += (price - lot_price) * close;
    let left = lot_qty - close;
    if left.abs() <= 1e-12 { lots.remove(select); } else { lots[select].0 = left; }
    remaining -= close;
  }
  if remaining.abs() > 1e-12 {
    if method == 3 {
      if let Some(existing) = lots.first_mut() {
        if existing.0 * remaining > 0.0 {
          let total = existing.0 + remaining;
          existing.1 = (existing.1 * existing.0.abs() + price * remaining.abs()) / total.abs();
          existing.0 = total;
          return realized;
        }
      }
    }
    lots.push((remaining, price));
  }
  realized
}

#[pyclass(unsendable)]
pub struct NativeGroupSession {
  factor: Py<numpy::PyArray2<f64>>,
  prices: Py<numpy::PyArray2<f64>>,
  lot_sizes: Vec<f64>,
  split_count: i64,
  group_index: i64,
  enforce_cash: bool,
  round_to_lot: bool,
  target_scale: f64,
  margin_ratio: f64,
  cost_method: i32,
  daily_mtm: bool,
  fee_rates: Vec<(f64, f64)>,
  volume: Option<Py<numpy::PyArray2<f64>>>,
  volume_rate: f64,
  execution_delay: usize,
  target_weights: Option<Py<numpy::PyArray2<f64>>>,
  threshold_mode: i32,
  entry_threshold: f64,
  exit_threshold: f64,
  quantile_entry: f64,
  quantile_exit: f64,
  side_mode: i32,
  force_close_mask: Option<Py<numpy::PyArray2<bool>>>,
}

#[pymethods]
impl NativeGroupSession {
  #[new]
  #[pyo3(signature=(factor, prices, lot_sizes, split_count, group_index, enforce_cash=false, round_to_lot=true, target_scale=1.0, margin_ratio=1.0, cost_method=0, daily_mtm=false, fee_rates=Vec::new(), volume=None, volume_rate=1.0, execution_delay=0, target_weights=None, threshold_mode=-1, entry_threshold=0.0, exit_threshold=0.0, quantile_entry=0.8, quantile_exit=0.6, side_mode=0, force_close_mask=None))]
  fn new(
    py: Python<'_>, factor: Py<numpy::PyArray2<f64>>,
    prices: Py<numpy::PyArray2<f64>>, lot_sizes: Vec<f64>,
    split_count: i64, group_index: i64, enforce_cash: bool, round_to_lot: bool,
    target_scale: f64, margin_ratio: f64, cost_method: i32, daily_mtm: bool,
    fee_rates: Vec<(f64, f64)>, volume: Option<Py<numpy::PyArray2<f64>>>,
    volume_rate: f64, execution_delay: usize,
    target_weights: Option<Py<numpy::PyArray2<f64>>>, threshold_mode: i32,
    entry_threshold: f64, exit_threshold: f64, quantile_entry: f64,
    quantile_exit: f64, side_mode: i32,
    force_close_mask: Option<Py<numpy::PyArray2<bool>>>,
  ) -> PyResult<Self> {
    let factor_view = factor.bind(py).readonly();
    let price_view = prices.bind(py).readonly();
    let (rows, columns) = factor_view.as_array().dim();
    if price_view.as_array().dim() != (rows, columns) || lot_sizes.len() != columns {
      return Err(pyo3::exceptions::PyValueError::new_err("native group shape mismatch"));
    }
    if split_count <= 0 || group_index < 0 || group_index >= split_count {
      return Err(pyo3::exceptions::PyValueError::new_err("invalid group selection"));
    }
    Ok(Self { factor, prices, lot_sizes, split_count, group_index, enforce_cash, round_to_lot, target_scale, margin_ratio, cost_method, daily_mtm, fee_rates, volume, volume_rate, execution_delay, target_weights, threshold_mode, entry_threshold, exit_threshold, quantile_entry, quantile_exit, side_mode, force_close_mask })
  }

  fn run_event_driven(
    &self, py: Python<'_>, initial_cash: f64, fee_rate: f64,
  ) -> PyResult<(
    Vec<f64>, Vec<(usize, usize, f64, f64, f64, f64)>,
    Vec<(u64, usize, f64, f64, i32)>, Vec<(usize, u64, f64, f64, f64)>,
    Vec<(u64, usize, i32)>, Vec<(u64, usize, f64)>,
    Vec<(usize, u64, usize, f64, f64, f64, f64, f64)>,
    Vec<(usize, u8, u64, usize)>, Vec<(usize, u64, usize, f64)>,
  )> {
    use std::cmp::Reverse;
    use std::collections::BinaryHeap;
    let factor_view = self.factor.bind(py).readonly();
    let price_view = self.prices.bind(py).readonly();
    let factor = factor_view.as_array();
    let prices = price_view.as_array();
    let volume_view = self.volume.as_ref().map(|value| value.bind(py).readonly());
    let target_view = self.target_weights.as_ref().map(|value| value.bind(py).readonly());
    let force_close_view = self.force_close_mask.as_ref().map(|value| value.bind(py).readonly());
    let force_close = force_close_view.as_ref().map(|value| value.as_array());
    let volume = volume_view.as_ref().map(|value| value.as_array());
    let (rows, columns) = factor.dim();
    let mut positions = vec![0.0f64; columns];
    let mut cash = initial_cash;
    let mut lots: Vec<Vec<(f64, f64)>> = vec![Vec::new(); columns];
    let mut margins = vec![0.0f64; columns];
    let mut marks = vec![0.0f64; columns];
    let mut equity = vec![initial_cash; rows];
    let mut trades = Vec::new();
    let mut orders = Vec::new();
    let mut audits = Vec::new();
    let mut order_id = 0u64;
    let mut sequence = 0u64;
    let mut queue: BinaryHeap<Reverse<(usize, i32, u64, u64)>> = BinaryHeap::new();
    let mut queued: std::collections::HashMap<u64, (usize, f64, f64, usize)> = std::collections::HashMap::new();
    let mut cancels: Vec<(usize, u64, usize, f64)> = Vec::new();
    let mut active_targets = vec![f64::NAN; columns];
    let mut previous_long = vec![false; columns];
    let mut previous_short = vec![false; columns];
    let delayed = self.execution_delay > 0;
    let mut attempts = Vec::new();
    let mut constraints = Vec::new();
    let mut events = Vec::new();
    for row in (if delayed { 0 } else { 1 })..rows {
      if !delayed || row < rows.saturating_sub(1) {
        events.push((row, 0, 0, 0));
        queue.push(Reverse((row, 2, sequence, 0)));
        sequence += 1;
      }
      let signal_offset = if delayed { row } else { row - 1 };
      if let Some(volume_values) = volume {
        if row < volume_values.shape()[0] {
          let mut required = 0.0;
          let mut release = 0.0;
          let mut buys: Vec<(u64, f64)> = Vec::new();
          for (queued_id, (queued_column, queued_delta, _scale, queued_row)) in queued.iter() {
            if *queued_row != row { continue; }
            let price = prices[[row, *queued_column]];
            if *queued_delta > 0.0 {
              let capacity = (volume_values[[row, *queued_column]] * self.volume_rate).max(0.0);
              let capped = queued_delta.abs().min(capacity);
              required += capped * price;
              buys.push((*queued_id, capped));
            } else {
              release += -queued_delta * price;
            }
          }
          let available = (cash + release).max(0.0);
          if required > available + 1e-9 && required > 0.0 {
            let scale = available / required;
            for (buy_id, _capped) in buys {
              if let Some(entry) = queued.get_mut(&buy_id) { entry.2 = scale; }
            }
          }
        }
      }
      while let Some(Reverse((event_row, kind, _seq, payload))) = queue.peek().copied() {
        if event_row != row { break; }
        queue.pop();
        if kind == 2 {
          let mut ranked: Vec<usize> = (0..columns)
            .filter(|&index| factor[[signal_offset, index]].is_finite())
            .collect();
          ranked.sort_by(|&left, &right| {
            factor[[signal_offset, right]].partial_cmp(&factor[[signal_offset, left]])
              .unwrap_or(std::cmp::Ordering::Equal).then_with(|| left.cmp(&right))
          });
          let eligible = ranked.len();
          let bucket_size = eligible as f64 / self.split_count as f64;
          let start = (self.group_index as f64 * bucket_size).round_ties_even() as usize;
          let end = (((self.group_index + 1) as f64) * bucket_size).round_ties_even() as usize;
          let members = &ranked[start..end.min(eligible)];
          let current_equity = if self.margin_ratio < 1.0 {
            cash + fast_sum(margins.iter().copied())
          } else {
            cash + fast_sum((0..columns).map(|index| positions[index] * prices[[if delayed { row } else { row - 1 }, index]]))
          };
          let group_weight = if members.is_empty() { 0.0 } else { 1.0 / members.len() as f64 };
          let target_weights = target_view.as_ref().map(|value| value.as_array());
          let mut computed_weights = vec![0.0f64; columns];
          if self.threshold_mode >= 0 {
            let mut values = vec![f64::NAN; columns];
            for index in 0..columns {
              let price = prices[[row, index]];
              let value = factor[[signal_offset, index]];
              if price > 0.0 && value.is_finite() { values[index] = value; }
            }
            let mut long_members = select_threshold_side(
              &values, &previous_long, self.threshold_mode, self.entry_threshold,
              self.exit_threshold, self.quantile_entry, self.quantile_exit, true,
            );
            let mut short_members = select_threshold_side(
              &values, &previous_short, self.threshold_mode, self.entry_threshold,
              self.exit_threshold, self.quantile_entry, self.quantile_exit, false,
            );
            previous_long = long_members.clone();
            previous_short = short_members.clone();
            if self.side_mode == 0 { short_members.iter_mut().for_each(|value| *value = false); }
            if self.side_mode == 1 { long_members.iter_mut().for_each(|value| *value = false); }
            let long_count = long_members.iter().filter(|value| **value).count() as f64;
            let short_count = short_members.iter().filter(|value| **value).count() as f64;
            for index in 0..columns {
              computed_weights[index] = if self.side_mode == 2 {
                (if long_members[index] && long_count > 0.0 { 0.5 / long_count } else { 0.0 })
                  - (if short_members[index] && short_count > 0.0 { 0.5 / short_count } else { 0.0 })
              } else if self.side_mode == 1 {
                if short_members[index] && short_count > 0.0 { -1.0 / short_count } else { 0.0 }
              } else if long_members[index] && long_count > 0.0 { 1.0 / long_count } else { 0.0 };
            }
          }
          let mut deltas = vec![0.0f64; columns];
          let mut row_weight = vec![0.0f64; columns];
          for index in 0..columns {
            let price = prices[[row, index]];
            if price <= 0.0 { continue; }
            let lot = if self.lot_sizes[index] > 0.0 { self.lot_sizes[index] } else { 1.0 };
            let weight = if self.threshold_mode >= 0 {
              computed_weights[index]
            } else if let Some(values) = &target_weights {
              values[[signal_offset, index]]
            } else if members.contains(&index) { group_weight } else { 0.0 };
            let force_close_here = force_close.map(|mask| mask[[signal_offset, index]]).unwrap_or(false);
            let weight = if force_close_here { 0.0 } else { weight };
            row_weight[index] = weight;
            let target = weight * current_equity * self.target_scale / prices[[if delayed { row } else { row - 1 }, index]];
            let target = if self.round_to_lot { (target / lot).floor() * lot } else { target };
            deltas[index] = target - positions[index];
          }
          let mut live_delta = vec![0.0f64; columns];
          for (_live_id, (live_column, live_quantity, _live_scale, _live_row)) in queued.iter() {
            live_delta[*live_column] += *live_quantity;
          }
          let mut kept_columns = vec![false; columns];
          for index in 0..columns {
            if (delayed && row_weight[index].abs() <= 1e-12 && positions[index].abs() <= 1e-12) || live_delta[index].abs() <= 1e-12 { continue; }
            let target_absolute = if delayed && active_targets[index].is_finite() {
              active_targets[index]
            } else {
              positions[index] + deltas[index]
            };
            let projected = positions[index] + live_delta[index];
            if (target_absolute - projected).abs() <= 1e-12 { kept_columns[index] = true; }
          }
          let mut canceled_ids = Vec::new();
          for (live_id, (live_column, live_quantity, _live_scale, _live_row)) in queued.iter() {
            if !kept_columns[*live_column] && (!delayed || row_weight[*live_column].abs() > 1e-12 || positions[*live_column].abs() > 1e-12) {
              cancels.push((row, *live_id, *live_column, *live_quantity));
              canceled_ids.push(*live_id);
            }
          }
          for canceled_id in canceled_ids { queued.remove(&canceled_id); }
          let mut planned = Vec::new();
          let mut cash_capacity = 0.0;
          let mut cash_required = 0.0;
          let mut cash_scale = 1.0;
          if self.threshold_mode >= 0 {
            let mut release = 0.0;
            let mut required = 0.0;
            for index in 0..columns {
              let delta = deltas[index];
              if delta < 0.0 { release += -delta * prices[[row, index]]; }
              if delta > 0.0 { required += delta * prices[[row, index]]; }
            }
            cash_capacity = (cash + release).max(0.0);
            cash_required = required;
            cash_scale = if required > cash_capacity + 1e-9 { cash_capacity / required } else { 1.0 };
            for index in 0..columns {
              let delta = deltas[index];
              planned.push((index, if delta > 0.0 { delta * cash_scale } else { delta }));
            }
          } else if self.enforce_cash {
            let mut release = 0.0;
            let mut required = 0.0;
            for index in 0..columns {
              let delta = deltas[index];
              let capacity_weight = if self.margin_ratio < 1.0 { self.margin_ratio } else { 1.0 };
              if delta < 0.0 { release += -delta * prices[[row, index]] * capacity_weight; }
              if delta > 0.0 { required += delta * prices[[row, index]] * capacity_weight; }
            }
            cash_capacity = (cash + release).max(0.0);
            cash_required = required;
            cash_scale = if required > cash_capacity + 1e-9 { cash_capacity / required } else { 1.0 };
            for index in 0..columns {
              if deltas[index] < 0.0 { planned.push((index, deltas[index])); }
            }
            for index in 0..columns {
              if deltas[index] > 0.0 { planned.push((index, deltas[index] * cash_scale)); }
            }
          } else if volume.is_some() {
            for index in 0..columns {
              if deltas[index] < 0.0 { planned.push((index, deltas[index])); }
            }
            for index in 0..columns {
              if deltas[index] > 0.0 { planned.push((index, deltas[index])); }
            }
          } else {
            for index in 0..columns {
              planned.push((index, deltas[index]));
            }
          }
          let execution_row = if delayed { row + 1 + self.execution_delay } else { row + self.execution_delay };
          let mut execution_cash_scale = 1.0;
          if let Some(volume_values) = volume {
            if execution_row < rows {
              let mut required = 0.0;
              let mut release = 0.0;
              for (index, order_delta) in &planned {
                let price = prices[[execution_row, *index]];
                if *order_delta > 0.0 {
                  let capacity = (volume_values[[execution_row, *index]] * self.volume_rate).max(0.0);
                  required += order_delta.abs().min(capacity) * price;
                } else {
                  release += -order_delta * price;
                }
              }
              let available = (cash + release).max(0.0);
              if required > available + 1e-9 && required > 0.0 {
                execution_cash_scale = available / required;
              }
            }
          }
          let mut signal_order_ids = vec![0u64; columns];
          for index in 0..columns {
            if deltas[index].abs() <= 1e-12 || kept_columns[index] { continue; }
            order_id += 1;
            signal_order_ids[index] = order_id;
            attempts.push((order_id, row, 0));
            events.push((row, 1, order_id, index));
          }
          for (index, order_delta) in planned {
            if order_delta.abs() <= 1e-12 || signal_order_ids[index] == 0 { continue; }
            let queued_order_id = signal_order_ids[index];
            queued.insert(queued_order_id, (index, order_delta, 1.0, execution_row));
            if execution_row < rows {
              if self.enforce_cash && deltas[index] > 0.0 && cash_scale < 1.0 {
                constraints.push((execution_row, queued_order_id, index, deltas[index], order_delta, cash_scale, cash_capacity, cash_required));
              }
              queue.push(Reverse((execution_row, 1, sequence, queued_order_id)));
              sequence += 1;
            }
          }
        } else {
          let order_key = payload;
          let Some((index, intent_delta, fill_scale, _exec_row)) = queued.remove(&order_key) else { continue; };
          let mut delta = intent_delta;
          if let Some(volume_values) = volume {
            if row >= volume_values.shape()[0] { continue; }
            let capacity = volume_values[[row, index]] * self.volume_rate;
            if delta.abs() > capacity {
              delta = delta.signum() * capacity.max(0.0);
            }
          }
          if delta > 0.0 && fill_scale < 1.0 {
            delta *= fill_scale;
          }
          let price = prices[[row, index]];
          if delta.abs() <= 1e-12 {
            if intent_delta.abs() > 1e-12 {
              orders.push((order_key, index, intent_delta, 0.0, 1));
              audits.push((row, order_key, 0.0, price, 0.0));
            }
            continue;
          }
          let prior = positions[index];
          let mut parts: Vec<(u64, f64, f64)> = Vec::new();
          if self.threshold_mode >= 0 && prior.abs() > 1e-12 && prior * delta < 0.0 {
            let close_delta = -prior;
            let open_delta = delta - close_delta;
            order_id += 1;
            let open_key = order_id;
            events.push((row, 1, open_key, index));
            parts.push((order_key, close_delta, close_delta));
            if open_delta.abs() > 1e-12 { parts.push((open_key, open_delta, open_delta)); }
          } else {
            parts.push((order_key, intent_delta, delta));
          }
          for (part_order_id, part_intent, part_delta) in parts {
            if part_delta.abs() <= 1e-12 { continue; }
            let notional = part_delta * price;
            let effective_fee_rate = if self.fee_rates.is_empty() {
              fee_rate
            } else {
              let (open_rate, close_rate) = self.fee_rates[index];
              if positions[index] * part_delta < 0.0 { close_rate } else { open_rate }
            };
            let fee = notional.abs() * effective_fee_rate;
            if self.margin_ratio < 1.0 {
              let realized = update_native_lots(&mut lots[index], part_delta, price, self.cost_method);
              let margin_before = margins[index];
              let new_position = positions[index] + part_delta;
              let margin_after = new_position.abs() * price * self.margin_ratio;
              cash += margin_before - margin_after + realized - fee;
              margins[index] = margin_after;
              positions[index] = new_position;
              marks[index] = price;
            } else {
              cash -= notional + fee;
              positions[index] += part_delta;
            }
            if row < rows.saturating_sub(1) && part_delta.abs() + 1e-12 < part_intent.abs() {
              cancels.push((row, part_order_id, index, part_intent - part_delta));
            }
            attempts.push((part_order_id, row, 1));
            orders.push((part_order_id, index, part_intent, fee, 1));
            audits.push((row, part_order_id, part_delta, price, fee));
            trades.push((row, index, part_delta, price, fee, cash));
          }
        }
      }
      if self.margin_ratio < 1.0 {
        if self.daily_mtm {
          for index in 0..columns {
            let position = positions[index];
            if position.abs() <= 1e-15 { continue; }
            let mark = prices[[row, index]];
            let margin_before = margins[index];
            let margin_after = position.abs() * mark * self.margin_ratio;
            cash += (mark - marks[index]) * position + margin_before - margin_after;
            margins[index] = margin_after;
            marks[index] = mark;
          }
        }
        equity[row] = cash + margins.iter().sum::<f64>();
      } else {
        let mut value = cash;
        for index in 0..columns { value += positions[index] * prices[[row, index]]; }
        equity[row] = value;
      }
    }
    let mut pending = Vec::new();
    if rows > 0 {
      events.push((rows - 1, 0, 0, 0));
      let signal_offset = rows - 1;
      let mut ranked: Vec<usize> = (0..columns).collect();
      ranked.sort_by(|&left, &right| {
        factor[[signal_offset, right]].partial_cmp(&factor[[signal_offset, left]])
          .unwrap_or(std::cmp::Ordering::Equal).then_with(|| left.cmp(&right))
      });
      let bucket_size = columns as f64 / self.split_count as f64;
      let start = (self.group_index as f64 * bucket_size).round_ties_even() as usize;
      let end = (((self.group_index + 1) as f64) * bucket_size).round_ties_even() as usize;
      let members = &ranked[start..end.min(columns)];
      let group_weight = if members.is_empty() { 0.0 } else { 1.0 / members.len() as f64 };
      let mut final_weights = vec![0.0f64; columns];
      if let Some(values) = target_view.as_ref().map(|value| value.as_array()) {
        for index in 0..columns { final_weights[index] = values[[rows - 1, index]]; }
      } else if self.threshold_mode >= 0 {
        let mut values = vec![f64::NAN; columns];
        for index in 0..columns {
          let price = prices[[signal_offset, index]];
          let value = factor[[signal_offset, index]];
          if price > 0.0 && value.is_finite() { values[index] = value; }
        }
        let mut long_members = select_threshold_side(
          &values, &previous_long, self.threshold_mode, self.entry_threshold,
          self.exit_threshold, self.quantile_entry, self.quantile_exit, true,
        );
        let mut short_members = select_threshold_side(
          &values, &previous_short, self.threshold_mode, self.entry_threshold,
          self.exit_threshold, self.quantile_entry, self.quantile_exit, false,
        );
        if self.side_mode == 0 { short_members.iter_mut().for_each(|value| *value = false); }
        if self.side_mode == 1 { long_members.iter_mut().for_each(|value| *value = false); }
        let long_count = long_members.iter().filter(|value| **value).count() as f64;
        let short_count = short_members.iter().filter(|value| **value).count() as f64;
        for index in 0..columns {
          final_weights[index] = if self.side_mode == 2 {
            (if long_members[index] && long_count > 0.0 { 0.5 / long_count } else { 0.0 })
              - (if short_members[index] && short_count > 0.0 { 0.5 / short_count } else { 0.0 })
          } else if self.side_mode == 1 {
            if short_members[index] && short_count > 0.0 { -1.0 / short_count } else { 0.0 }
          } else if long_members[index] && long_count > 0.0 { 1.0 / long_count } else { 0.0 };
        }
      }
      let current_equity = if self.margin_ratio < 1.0 {
        cash + fast_sum(margins.iter().copied())
      } else {
        cash + fast_sum((0..columns).map(|index| positions[index] * prices[[signal_offset, index]]))
      };
      let weight = if members.is_empty() { 0.0 } else { 1.0 / members.len() as f64 };
      for index in 0..columns {
        let price = prices[[signal_offset, index]];
        if price <= 0.0 { continue; }
        let lot = if self.lot_sizes[index] > 0.0 { self.lot_sizes[index] } else { 1.0 };
        let weight = if self.threshold_mode >= 0 { final_weights[index] } else if members.contains(&index) { group_weight } else { 0.0 };
        let target = weight * current_equity * self.target_scale / price;
        let target = if self.round_to_lot { (target / lot).floor() * lot } else { target };
        let order_delta = target - positions[index];
        if order_delta.abs() > 1e-12 {
          order_id += 1;
          pending.push((order_id, index, order_delta));
          attempts.push((order_id, signal_offset, 0));
        }
      }
    }
    Ok((equity, trades, orders, audits, attempts, pending, constraints, events, cancels))
  }

  fn run(
    &self, py: Python<'_>, initial_cash: f64, fee_rate: f64,
  ) -> PyResult<(
    Vec<f64>, Vec<(usize, usize, f64, f64, f64, f64)>,
    Vec<(u64, usize, f64, f64, i32)>, Vec<(usize, u64, f64, f64, f64)>,
  )> {
    let factor_view = self.factor.bind(py).readonly();
    let price_view = self.prices.bind(py).readonly();
    let factor = factor_view.as_array();
    let prices = price_view.as_array();
    let (rows, columns) = factor.dim();
    let mut positions = vec![0.0f64; columns];
    let mut cash = initial_cash;
    let mut equity = vec![initial_cash; rows];
    let mut trades = Vec::new();
    let mut orders = Vec::new();
    let mut audits = Vec::new();
    let mut order_id = 0u64;
    for row in 1..rows {
      let signal_offset = row - 1;
      let mut ranked: Vec<usize> = (0..columns)
        .filter(|&index| factor[[signal_offset, index]].is_finite())
        .collect();
      ranked.sort_by(|&left, &right| {
        factor[[signal_offset, right]].partial_cmp(&factor[[signal_offset, left]])
          .unwrap_or(std::cmp::Ordering::Equal)
          .then_with(|| left.cmp(&right))
      });
      let eligible = ranked.len();
      let bucket_size = eligible as f64 / self.split_count as f64;
      let start = (self.group_index as f64 * bucket_size).round_ties_even() as usize;
      let end = (((self.group_index + 1) as f64) * bucket_size).round_ties_even() as usize;
      let members = &ranked[start..end.min(eligible)];
      let mut current_equity = cash;
      for column in 0..columns {
        current_equity += positions[column] * prices[[row - 1, column]];
      }
      let weight = if members.is_empty() { 0.0 } else { 1.0 / members.len() as f64 };
      for column in 0..columns {
        let price = prices[[row, column]];
        if price <= 0.0 { continue; }
        let lot = if self.lot_sizes[column] > 0.0 { self.lot_sizes[column] } else { 1.0 };
        let target = if members.contains(&column) { weight * current_equity * self.target_scale / prices[[row - 1, column]] } else { 0.0 };
        let target = if self.round_to_lot { (target / lot).floor() * lot } else { target };
        let delta = target - positions[column];
        if delta.abs() <= 1e-12 { continue; }
        let notional = delta * price;
        let effective_fee_rate = if self.fee_rates.is_empty() {
          fee_rate
        } else {
          let (open_rate, close_rate) = self.fee_rates[column];
          if positions[column] * delta < 0.0 { close_rate } else { open_rate }
        };
        let fee = notional.abs() * effective_fee_rate;
        cash -= notional + fee;
        positions[column] = target;
        order_id += 1;
        orders.push((order_id, column, delta, fee, 1));
        audits.push((row, order_id, delta, price, fee));
        trades.push((row, column, delta, price, fee, cash));
      }
      let mut value = cash;
      for column in 0..columns {
        value += positions[column] * prices[[row, column]];
      }
      equity[row] = value;
    }
    Ok((equity, trades, orders, audits))
  }
}

#[pyclass(unsendable)]
pub struct NativeSession {
  prices: Py<numpy::PyArray2<f64>>,
  targets: Py<numpy::PyArray2<f64>>,
  lot_sizes: Vec<f64>,
}

#[pymethods]
impl NativeSession {
  #[new]
  fn new(
    py: Python<'_>, prices: Py<numpy::PyArray2<f64>>,
    targets: Py<numpy::PyArray2<f64>>, lot_sizes: Vec<f64>,
  ) -> PyResult<Self> {
    let price_view = prices.bind(py).readonly();
    let target_view = targets.bind(py).readonly();
    let (rows, columns) = price_view.as_array().dim();
    if target_view.as_array().dim() != (rows, columns) || lot_sizes.len() != columns {
      return Err(pyo3::exceptions::PyValueError::new_err("native session shape mismatch"));
    }
    Ok(Self { prices, targets, lot_sizes })
  }

  fn run_with_lifecycle(
    &self, py: Python<'_>, initial_cash: f64, fee_rate: f64,
  ) -> PyResult<(
    Vec<f64>, Vec<(usize, usize, f64, f64, f64, f64)>,
    Vec<(u64, usize, f64, f64, i32)>,
    Vec<(usize, u64, f64, f64, f64)>,
  )> {
    let price_view = self.prices.bind(py).readonly();
    let target_view = self.targets.bind(py).readonly();
    let prices = price_view.as_array();
    let targets = target_view.as_array();
    let (rows, columns) = prices.dim();
    let mut positions = vec![0.0f64; columns];
    let mut cash = initial_cash;
    let mut equity = vec![initial_cash; rows];
    let mut trades = Vec::new();
    let mut orders = Vec::new();
    let mut audits = Vec::new();
    let mut order_id = 0u64;
    for row in 1..rows {
      let mut current_equity = cash;
      for column in 0..columns {
        current_equity += positions[column] * prices[[row - 1, column]];
      }
      for column in 0..columns {
        let price = prices[[row, column]];
        if price <= 0.0 { continue; }
        let lot = if self.lot_sizes[column] > 0.0 { self.lot_sizes[column] } else { 1.0 };
        let target = targets[[row - 1, column]] * current_equity / prices[[row - 1, column]];
        let target = (target / lot).floor() * lot;
        let delta = target - positions[column];
        if delta.abs() <= 1e-12 { continue; }
        let notional = delta * price;
        let fee = notional.abs() * fee_rate;
        cash -= notional + fee;
        positions[column] = target;
        order_id += 1;
        orders.push((order_id, column, delta, fee, 1));
        audits.push((row, order_id, delta, price, fee));
        trades.push((row, column, delta, price, fee, cash));
      }
      let mut value = cash;
      for column in 0..columns {
        value += positions[column] * prices[[row, column]];
      }
      equity[row] = value;
    }
    Ok((equity, trades, orders, audits))
  }

  fn run(
    &self, py: Python<'_>, initial_cash: f64, fee_rate: f64,
  ) -> PyResult<(Vec<f64>, Vec<(usize, usize, f64, f64, f64, f64)>)> {
    let price_view = self.prices.bind(py).readonly();
    let target_view = self.targets.bind(py).readonly();
    let prices = price_view.as_array();
    let targets = target_view.as_array();
    let (rows, columns) = prices.dim();
    let mut positions = vec![0.0f64; columns];
    let mut cash = initial_cash;
    let mut equity = vec![initial_cash; rows];
    let mut trades = Vec::new();
    for row in 1..rows {
      let mut current_equity = cash;
      for column in 0..columns {
        current_equity += positions[column] * prices[[row - 1, column]];
      }
      for column in 0..columns {
        let price = prices[[row, column]];
        if price <= 0.0 { continue; }
        let lot = if self.lot_sizes[column] > 0.0 { self.lot_sizes[column] } else { 1.0 };
        let target = targets[[row - 1, column]] * current_equity / prices[[row - 1, column]];
        let target = (target / lot).floor() * lot;
        let delta = target - positions[column];
        if delta.abs() <= 1e-12 { continue; }
        let notional = delta * price;
        let fee = notional.abs() * fee_rate;
        cash -= notional + fee;
        positions[column] = target;
        trades.push((row, column, delta, price, fee, cash));
      }
      let mut value = cash;
      for column in 0..columns {
        value += positions[column] * prices[[row, column]];
      }
      equity[row] = value;
    }
    Ok((equity, trades))
  }
}

#[pyclass(unsendable)]
pub struct CashConstraintKernel;

#[pymethods]
impl CashConstraintKernel {
  #[new]
  fn new() -> Self { Self }

  fn basic_constraint(
    &self, available: f64, prior: Vec<f64>, order_quantities: Vec<f64>,
    prices: Vec<f64>, multipliers: Vec<f64>,
  ) -> PyResult<(f64, f64, f64, Vec<f64>, Vec<f64>, Vec<bool>)> {
    let count = prior.len();
    if order_quantities.len() != count || prices.len() != count || multipliers.len() != count {
      return Err(pyo3::exceptions::PyValueError::new_err("cash constraint length mismatch"));
    }
    let mut reducing = vec![0.0; count];
    let mut increasing = vec![0.0; count];
    for index in 0..count {
      let order_quantity = order_quantities[index];
      if order_quantity.abs() <= 1e-12 { continue; }
      let prior_quantity = prior[index];
      if prior_quantity.abs() <= 1e-12 || prior_quantity * order_quantity > 0.0 {
        increasing[index] = order_quantity;
      } else {
        let close_abs = prior_quantity.abs().min(order_quantity.abs());
        let sign = if order_quantity > 0.0 { 1.0 } else { -1.0 };
        reducing[index] = sign * close_abs;
        increasing[index] = order_quantity - reducing[index];
      }
    }
    let mut release = 0.0;
    let mut required = 0.0;
    let mut constrained = vec![false; count];
    for index in 0..count {
      let price_multiplier = prices[index] * multipliers[index];
      release += -reducing[index] * price_multiplier;
      let delta = -increasing[index] * price_multiplier;
      if delta < -1e-12 {
        required += -delta;
        constrained[index] = true;
      }
    }
    let capacity = (available + release).max(0.0);
    let scale = if required <= capacity + 1e-9 {
      1.0
    } else if required <= 0.0 {
      0.0
    } else {
      capacity / required
    };
    if scale >= 1.0 {
      constrained.iter_mut().for_each(|value| *value = false);
    }
    Ok((release, required, scale, reducing, increasing, constrained))
  }
}

fn select_threshold_side(
  values: &[f64], previous: &[bool], mode: i32,
  entry: f64, exit: f64, quantile_entry: f64, quantile_exit: f64,
  positive_side: bool,
) -> Vec<bool> {
  let entry_cutoff = if mode == 1 {
    quantile_cutoff(values, quantile_entry, positive_side)
  } else if positive_side { entry } else { -entry };
  let exit_cutoff = if mode == 1 {
    quantile_cutoff(values, quantile_exit, positive_side)
  } else if positive_side { exit } else { -exit };
  values.iter().enumerate().map(|(index, value)| {
    let passes_entry = if positive_side { *value >= entry_cutoff } else { *value <= entry_cutoff };
    let passes_exit = if positive_side { *value >= exit_cutoff } else { *value <= exit_cutoff };
    passes_entry || (previous[index] && passes_exit)
  }).collect()
}

#[pyclass(unsendable)]
pub struct LongShortKernel;

#[pymethods]
impl LongShortKernel {
  #[new]
  fn new() -> Self { Self }

  fn compose(&self, long_weights: Vec<f64>, short_weights: Vec<f64>, gross: f64) -> PyResult<Vec<f64>> {
    let count = long_weights.len();
    if short_weights.len() != count {
      return Err(pyo3::exceptions::PyValueError::new_err("long-short length mismatch"));
    }
    let mut long_total = 0.0f64;
    let mut short_total = 0.0f64;
    for index in 0..count {
      if long_weights[index].abs() > 1e-12 && short_weights[index].abs() > 1e-12 { continue; }
      long_total += long_weights[index].abs();
      short_total += short_weights[index].abs();
    }
    if long_total <= 0.0 || short_total <= 0.0 {
      return Ok(vec![0.0; count]);
    }
    let half = gross.abs() * 0.5;
    Ok((0..count).map(|index| {
      let long = if long_weights[index].abs() > 1e-12 && short_weights[index].abs() <= 1e-12 {
        half * long_weights[index].abs() / long_total
      } else { 0.0 };
      let short = if short_weights[index].abs() > 1e-12 && long_weights[index].abs() <= 1e-12 {
        half * short_weights[index].abs() / short_total
      } else { 0.0 };
      long - short
    }).collect())
  }
}

#[pyclass(unsendable)]
pub struct LifecycleKernel;

#[pymethods]
impl LifecycleKernel {
  #[new]
  fn new() -> Self { Self }

  fn parse_offset_seconds(&self, value: &str) -> PyResult<f64> {
    let text = value.trim();
    if text.is_empty() { return Ok(0.0); }
    let mut split = text.find(|character: char| !character.is_ascii_digit() && character != '.').unwrap_or(text.len());
    if split == 0 { return Err(pyo3::exceptions::PyValueError::new_err("invalid time offset")); }
    let number: f64 = text[..split].parse().map_err(|_| pyo3::exceptions::PyValueError::new_err("invalid time offset"))?;
    let unit = text[split..].trim().to_ascii_lowercase();
    split = 0;
    let factor = match unit.as_str() {
      "d" | "day" | "days" => 86_400.0,
      "h" | "hour" | "hours" => 3_600.0,
      "min" | "minute" | "minutes" => 60.0,
      "s" | "sec" | "second" | "seconds" => 1.0,
      "ms" => 0.001,
      "us" => 0.000001,
      "" => 86_400.0,
      _ => return Err(pyo3::exceptions::PyValueError::new_err("invalid time offset")),
    };
    let seconds = number * factor;
    if seconds < 0.0 { return Err(pyo3::exceptions::PyValueError::new_err("invalid time offset")); }
    Ok(seconds)
  }
}

#[pyclass(unsendable)]
pub struct TermCarryKernel;

#[pymethods]
impl TermCarryKernel {
  #[new]
  fn new() -> Self { Self }

  fn next_direction(&self, signal: f64, previous: i32, entry: f64, exit_at: f64) -> i32 {
    if !signal.is_finite() { return previous; }
    let entry = entry.abs();
    let exit_at = exit_at.abs();
    if signal.abs() <= exit_at { 0 }
    else if signal >= entry { 1 }
    else if signal <= -entry { -1 }
    else { previous }
  }

  fn leg_weights(&self, direction: i32, gross: f64, product_count: usize) -> PyResult<Vec<f64>> {
    if product_count == 0 { return Ok(vec![0.0, 0.0]); }
    let leg_weight = gross.abs() / (2.0 * product_count as f64);
    Ok(vec![direction as f64 * leg_weight, -(direction as f64) * leg_weight])
  }
}

#[pyclass(unsendable)]
pub struct GroupKernel;

#[pymethods]
impl GroupKernel {
  #[new]
  fn new() -> Self { Self }

  fn equal_group_weights(
    &self, values: Vec<f64>, prices: Vec<f64>, split_count: i64, group_index: i64,
  ) -> PyResult<Vec<f64>> {
    let count = values.len();
    if prices.len() != count || split_count <= 0 || group_index < 0 || group_index >= split_count {
      return Err(pyo3::exceptions::PyValueError::new_err("invalid group selection"));
    }
    let mut ranked: Vec<usize> = (0..count)
      .filter(|&index| values[index].is_finite() && prices[index] > 0.0)
      .collect();
    ranked.sort_by(|&left, &right| {
      values[right].partial_cmp(&values[left])
        .unwrap_or(std::cmp::Ordering::Equal)
        .then_with(|| left.cmp(&right))
    });
    let eligible = ranked.len();
    let bucket_size = eligible as f64 / split_count as f64;
    let start = (group_index as f64 * bucket_size).round_ties_even() as usize;
    let end = (((group_index + 1) as f64) * bucket_size).round_ties_even() as usize;
    let members = &ranked[start..end.min(eligible)];
    let weight = if members.is_empty() { 0.0 } else { 1.0 / members.len() as f64 };
    let mut weights = vec![0.0f64; count];
    for index in 0..count {
      if prices[index] > 0.0 && members.contains(&index) { weights[index] = weight; }
    }
    Ok(weights)
  }
}

#[pyclass(unsendable)]
pub struct ThresholdKernel;

#[pymethods]
impl ThresholdKernel {
  #[new]
  fn new() -> Self { Self }

  fn select_side(
    &self, values: Vec<f64>, previous: Vec<bool>, mode: &str,
    entry: f64, exit: f64, quantile_entry: f64, quantile_exit: f64,
    positive_side: bool,
  ) -> PyResult<Vec<bool>> {
    if values.len() != previous.len() {
      return Err(pyo3::exceptions::PyValueError::new_err("threshold length mismatch"));
    }
    let entry_cutoff = if mode == "cross_section_quantile" {
      quantile_cutoff(&values, quantile_entry, positive_side)
    } else if positive_side { entry } else { -entry };
    let exit_cutoff = if mode == "cross_section_quantile" {
      quantile_cutoff(&values, quantile_exit, positive_side)
    } else if positive_side { exit } else { -exit };
    Ok(values.iter().enumerate().map(|(index, value)| {
      let passes_entry = if positive_side { *value >= entry_cutoff } else { *value <= entry_cutoff };
      let passes_exit = if positive_side { *value >= exit_cutoff } else { *value <= exit_cutoff };
      (passes_entry) || (previous[index] && passes_exit)
    }).collect())
  }

  fn equal_weights(
    &self, long_members: Vec<bool>, short_members: Vec<bool>, side_mode: &str,
  ) -> PyResult<Vec<f64>> {
    let count = long_members.len();
    if short_members.len() != count {
      return Err(pyo3::exceptions::PyValueError::new_err("threshold length mismatch"));
    }
    let long_count = long_members.iter().filter(|value| **value).count() as f64;
    let short_count = short_members.iter().filter(|value| **value).count() as f64;
    let mut weights = vec![0.0f64; count];
    if side_mode == "long_short_spread" {
      for index in 0..count {
        let long = if long_members[index] && long_count > 0.0 { 0.5 / long_count } else { 0.0 };
        let short = if short_members[index] && short_count > 0.0 { 0.5 / short_count } else { 0.0 };
        weights[index] = long - short;
      }
    } else if side_mode == "short_only" {
      if short_count > 0.0 {
        for index in 0..count { if short_members[index] { weights[index] = -1.0 / short_count; } }
      }
    } else if long_count > 0.0 {
      for index in 0..count { if long_members[index] { weights[index] = 1.0 / long_count; } }
    }
    Ok(weights)
  }
}

fn quantile_cutoff(values: &[f64], quantile: f64, positive_side: bool) -> f64 {
  let mut sorted: Vec<f64> = values.iter().copied().filter(|value| value.is_finite()).collect();
  if sorted.is_empty() { return f64::NAN; }
  sorted.sort_by(|left, right| left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal));
  let q = quantile.clamp(0.0, 1.0);
  let q = if positive_side { q } else { 1.0 - q };
  let position = q * (sorted.len() - 1) as f64;
  let lower = position.floor() as usize;
  let upper = position.ceil() as usize;
  let fraction = position - lower as f64;
  sorted[lower] + (sorted[upper] - sorted[lower]) * fraction
}

#[pyclass(unsendable)]
pub struct OrderConstructionKernel;

#[pymethods]
impl OrderConstructionKernel {
  #[new]
  fn new() -> Self { Self }

  fn close_buckets(
    &self, close_quantity: f64, lot_quantities: Vec<f64>,
    lot_today: Vec<i32>, lot_prices: Vec<f64>, method: i32,
  ) -> PyResult<Vec<(i32, i32, f64)>> {
    let count = lot_quantities.len();
    if lot_today.len() != count || lot_prices.len() != count {
      return Err(pyo3::exceptions::PyValueError::new_err("lot bucket length mismatch"));
    }
    if close_quantity <= 1e-12 { return Ok(Vec::new()); }
    if count == 0 { return Ok(vec![(2, 3, close_quantity)]); }
    let mut order: Vec<usize> = (0..count).collect();
    if method == 1 { order.reverse(); }
    else if method == 2 {
      order.sort_by(|&left, &right| lot_prices[right].partial_cmp(&lot_prices[left]).unwrap_or(std::cmp::Ordering::Equal));
    }
    let mut buckets: Vec<(i32, i32, f64)> = Vec::new();
    let mut remaining = close_quantity;
    for index in order {
      if remaining <= 1e-12 { break; }
      let take = remaining.min(lot_quantities[index].abs());
      let (offset, role) = match lot_today[index] {
        1 => (3, 1),
        0 => (4, 2),
        _ => (2, 3),
      };
      if let Some(bucket) = buckets.iter_mut().find(|bucket| bucket.0 == offset && bucket.1 == role) {
        bucket.2 += take;
      } else {
        buckets.push((offset, role, take));
      }
      remaining -= take;
    }
    if remaining > 1e-12 {
      if let Some(bucket) = buckets.iter_mut().find(|bucket| bucket.0 == 2 && bucket.1 == 3) {
        bucket.2 += remaining;
      } else {
        buckets.push((2, 3, remaining));
      }
    }
    Ok(buckets)
  }
}

#[pyclass(unsendable)]
pub struct OrderLifecycleBatch {
  accepted: Vec<f64>,
  filled: Vec<f64>,
}

#[pymethods]
impl OrderLifecycleBatch {
  #[new]
  fn new(accepted: Vec<f64>, filled: Vec<f64>) -> PyResult<Self> {
    if accepted.len() != filled.len() {
      return Err(pyo3::exceptions::PyValueError::new_err("lifecycle batch length mismatch"));
    }
    Ok(Self { accepted, filled })
  }

  fn apply_fills(
    &mut self, indices: Vec<usize>, quantities: Vec<f64>,
  ) -> PyResult<Vec<(usize, f64, bool)>> {
    let length = indices.len();
    if quantities.len() != length {
      return Err(pyo3::exceptions::PyValueError::new_err("fill batch length mismatch"));
    }
    let mut result = Vec::with_capacity(length);
    for position in 0..length {
      let index = indices[position];
      if index >= self.accepted.len() {
        return Err(pyo3::exceptions::PyIndexError::new_err("lifecycle index out of range"));
      }
      let quantity = quantities[position];
      if quantity <= 0.0 {
        return Err(pyo3::exceptions::PyValueError::new_err("fill quantity must be positive"));
      }
      let remaining = (self.accepted[index] - self.filled[index]).max(0.0);
      if quantity > remaining + 1e-12 {
        return Err(pyo3::exceptions::PyValueError::new_err("fill exceeds remaining quantity"));
      }
      self.filled[index] += quantity;
      let completed = self.accepted[index] - self.filled[index] <= 1e-12;
      result.push((index, self.filled[index], completed));
    }
    Ok(result)
  }

  fn remaining(&self) -> Vec<f64> {
    (0..self.accepted.len())
      .map(|index| (self.accepted[index] - self.filled[index]).max(0.0))
      .collect()
  }
}

#[pyclass(unsendable)]
pub struct TargetAllocator;

#[pymethods]
impl TargetAllocator {
  #[new]
  fn new() -> Self { Self }

  fn equal_weights(&self, count: usize) -> Vec<f64> {
    if count == 0 { return Vec::new(); }
    vec![1.0 / count as f64; count]
  }

  fn inverse_measure_weights(
    &self, measures: Vec<f64>, present: Vec<bool>, missing_equal_share: bool,
  ) -> PyResult<Vec<f64>> {
    let count = measures.len();
    if present.len() != count {
      return Err(pyo3::exceptions::PyValueError::new_err("measure batch length mismatch"));
    }
    if count == 0 { return Ok(Vec::new()); }
    let mut inverse_total = 0.0;
    let mut inverse = vec![0.0; count];
    for index in 0..count {
      if present[index] && measures[index] > 0.0 {
        inverse[index] = 1.0 / measures[index];
        inverse_total += inverse[index];
      }
    }
    if inverse_total <= 0.0 {
      return Ok(vec![1.0 / count as f64; count]);
    }
    let mut weights = vec![0.0; count];
    if missing_equal_share {
      let missing_count = (0..count).filter(|&index| inverse[index] == 0.0).count();
      let available_share = 1.0 - missing_count as f64 / count as f64;
      let equal_share = 1.0 / count as f64;
      for index in 0..count {
        weights[index] = if inverse[index] > 0.0 {
          available_share * inverse[index] / inverse_total
        } else {
          equal_share
        };
      }
    } else {
      for index in 0..count {
        weights[index] = inverse[index] / inverse_total;
      }
    }
    Ok(weights)
  }

  fn rank_indices(
    &self, values: Vec<f64>, names: Vec<String>, descending: bool,
  ) -> PyResult<Vec<usize>> {
    if names.len() != values.len() {
      return Err(pyo3::exceptions::PyValueError::new_err("rank batch length mismatch"));
    }
    let mut indices: Vec<usize> = (0..values.len()).collect();
    indices.sort_by(|&left, &right| {
      let ordering = values[left].partial_cmp(&values[right]).unwrap_or(std::cmp::Ordering::Equal);
      let ordering = if descending { ordering.reverse() } else { ordering };
      ordering.then_with(|| names[left].cmp(&names[right]))
    });
    Ok(indices)
  }

  fn screen_mask(
    &self, values: Vec<f64>, present: Vec<bool>, rule: i32,
    lower: f64, upper: f64,
  ) -> PyResult<Vec<bool>> {
    let count = values.len();
    if present.len() != count {
      return Err(pyo3::exceptions::PyValueError::new_err("screen batch length mismatch"));
    }
    let mut mask = vec![false; count];
    for index in 0..count {
      let value = values[index];
      if !present[index] || !value.is_finite() { continue; }
      mask[index] = match rule {
        1 => value >= lower,
        2 => value <= upper,
        3 => lower <= value && value <= upper,
        _ => true,
      };
    }
    Ok(mask)
  }

  fn factor_weights(
    &self, values: Vec<f64>, present: Vec<bool>, inverse: bool,
  ) -> PyResult<Vec<f64>> {
    let count = values.len();
    if present.len() != count {
      return Err(pyo3::exceptions::PyValueError::new_err("factor batch length mismatch"));
    }
    let mut raw = vec![0.0; count];
    for index in 0..count {
      let value = values[index];
      if present[index] && value.is_finite() && value > 0.0 {
        raw[index] = if inverse { 1.0 / value } else { value };
      }
    }
    let total: f64 = raw.iter().sum();
    if total <= 0.0 { return Ok(vec![0.0; count]); }
    Ok(raw.into_iter().map(|value| value / total).collect())
  }
}

#[pyclass(unsendable)]
pub struct FeeModel;

#[pymethods]
impl FeeModel {
  #[new]
  fn new() -> Self { Self }

  fn split_open_close(&self, quantity: f64, current_quantity: f64) -> (f64, f64) {
    if quantity == 0.0 { return (0.0, 0.0); }
    if current_quantity == 0.0 || (quantity > 0.0) == (current_quantity > 0.0) {
      return (quantity.abs(), 0.0);
    }
    let close_qty = quantity.abs().min(current_quantity.abs());
    ((quantity.abs() - close_qty).max(0.0), close_qty)
  }

  fn split_close_today_yesterday(
    &self, close_qty: f64, lot_quantities: Vec<f64>, lot_today: Vec<bool>,
    lot_prices: Vec<f64>, policy: i32, method: i32,
  ) -> PyResult<(f64, f64)> {
    let count = lot_quantities.len();
    if lot_today.len() != count || lot_prices.len() != count {
      return Err(pyo3::exceptions::PyValueError::new_err("lot split length mismatch"));
    }
    if close_qty <= 1e-12 { return Ok((0.0, 0.0)); }
    if policy == 1 { return Ok((close_qty, 0.0)); }
    if policy == 2 || policy == 3 { return Ok((0.0, close_qty)); }
    let mut order: Vec<usize> = (0..count).collect();
    if method == 1 { order.reverse(); }
    else if method == 2 {
      order.sort_by(|&left, &right| lot_prices[right].partial_cmp(&lot_prices[left]).unwrap_or(std::cmp::Ordering::Equal));
    }
    let mut remaining = close_qty;
    let mut today = 0.0;
    let mut yesterday = 0.0;
    for index in order {
      if remaining <= 1e-12 { break; }
      let take = remaining.min(lot_quantities[index].abs());
      if lot_today[index] { today += take; } else { yesterday += take; }
      remaining -= take;
    }
    Ok((today, yesterday + remaining.max(0.0)))
  }

  fn market_fee(
    &self, open_quantity: f64, close_yesterday: f64, close_today: f64,
    price: f64, multiplier: f64,
    open_ratio: f64, open_fixed: f64,
    close_ratio: f64, close_fixed: f64,
    close_today_ratio: f64, close_today_fixed: f64,
  ) -> f64 {
    let open_fee = open_quantity.abs() * (price * multiplier * open_ratio + open_fixed);
    let close_fee = close_yesterday.abs() * (price * multiplier * close_ratio + close_fixed);
    let today_fee = close_today.abs() * (price * multiplier * close_today_ratio + close_today_fixed);
    open_fee + close_fee + today_fee
  }

  fn fixed_fee_batch(
    &self, quantities: Vec<f64>, prices: Vec<f64>,
    multipliers: Vec<f64>, rate: f64,
  ) -> PyResult<Vec<f64>> {
    let length = quantities.len();
    if prices.len() != length || multipliers.len() != length {
      return Err(pyo3::exceptions::PyValueError::new_err("fee batch length mismatch"));
    }
    Ok((0..length).map(|index| {
      (quantities[index] * prices[index] * multipliers[index]).abs() * rate
    }).collect())
  }
}

#[pyclass(unsendable)]
pub struct VectorBacktest {
  rows: usize,
  columns: usize,
  prices: Py<numpy::PyArray2<f64>>,
  targets: Py<numpy::PyArray2<f64>>,
}

#[pymethods]
impl VectorBacktest {
  #[new]
  fn new(
    py: Python<'_>, prices: Py<numpy::PyArray2<f64>>,
    targets: Py<numpy::PyArray2<f64>>,
  ) -> PyResult<Self> {
    let price_view = prices.bind(py).readonly();
    let target_view = targets.bind(py).readonly();
    let price_array = price_view.as_array();
    let target_array = target_view.as_array();
    let (rows, columns) = price_array.dim();
    if target_array.dim() != (rows, columns) {
      return Err(pyo3::exceptions::PyValueError::new_err("shape mismatch"));
    }
    Ok(Self { rows, columns, prices, targets })
  }

  fn run(&self, py: Python<'_>, initial_cash: f64, fee_rate: f64, lot_sizes: Vec<f64>) -> Vec<f64> {
    let price_view = self.prices.bind(py).readonly();
    let target_view = self.targets.bind(py).readonly();
    let prices = price_view.as_array();
    let targets = target_view.as_array();
    let mut positions = vec![0.0f64; self.columns];
    let mut cash = initial_cash;
    let mut equity = vec![initial_cash; self.rows];
    for row in 1..self.rows {
      let mut current_equity = cash;
      for column in 0..self.columns {
        current_equity += positions[column] * prices[[row, column]];
      }
      let mut fees = 0.0;
      let mut cash_flow = 0.0;
      for column in 0..self.columns {
        let price = prices[[row, column]];
        if price <= 0.0 { continue; }
        let lot = if lot_sizes[column] > 0.0 { lot_sizes[column] } else { 1.0 };
        let target = targets[[row - 1, column]] * current_equity / price;
        let target = (target / lot).floor() * lot;
        let delta = target - positions[column];
        cash_flow += delta * price;
        fees += (delta * price).abs() * fee_rate;
        positions[column] = target;
      }
      cash -= cash_flow + fees;
      let mut value = cash;
      for column in 0..self.columns {
        value += positions[column] * prices[[row, column]];
      }
      equity[row] = value;
    }
    equity
  }
}

#[pyclass(unsendable)]
pub struct OrderAttemptRecord {
  attempt_id: String,
  order_id: String,
  revision: i32,
  timestamp: Py<PyAny>,
  market_timestamp: Py<PyAny>,
  order: Py<PyAny>,
}

#[pymethods]
impl OrderAttemptRecord {
  #[getter] fn attempt_id(&self) -> &str { &self.attempt_id }
  #[getter] fn order_id(&self) -> &str { &self.order_id }
  #[getter] fn revision(&self) -> i32 { self.revision }
  #[getter] fn timestamp(&self, py: Python<'_>) -> Py<PyAny> { self.timestamp.clone_ref(py) }
  #[getter] fn market_timestamp(&self, py: Python<'_>) -> Py<PyAny> { self.market_timestamp.clone_ref(py) }
  #[getter] fn order(&self, py: Python<'_>) -> Py<PyAny> { self.order.clone_ref(py) }

  fn to_audit_dict(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
    let dict = pyo3::types::PyDict::new(py);
    dict.set_item(pyo3::intern!(py, "type"), "OrderAttempt")?;
    dict.set_item(pyo3::intern!(py, "attempt_id"), &self.attempt_id)?;
    dict.set_item(pyo3::intern!(py, "order_id"), &self.order_id)?;
    dict.set_item(pyo3::intern!(py, "revision"), self.revision)?;
    dict.set_item(pyo3::intern!(py, "timestamp"), self.timestamp.clone_ref(py))?;
    dict.set_item(pyo3::intern!(py, "market_timestamp"), self.market_timestamp.clone_ref(py))?;
    Ok(dict.into())
  }
}

#[pyfunction]
fn create_attempt_records(
  py: Python<'_>, attempt_ids: Vec<String>, order_ids: Vec<String>,
  revisions: Vec<i32>, timestamps: Vec<Py<PyAny>>,
  market_timestamps: Vec<Py<PyAny>>, orders: Vec<Py<PyAny>>,
) -> PyResult<Vec<Py<OrderAttemptRecord>>> {
  let length = attempt_ids.len();
  if order_ids.len() != length || revisions.len() != length
    || timestamps.len() != length || market_timestamps.len() != length
    || orders.len() != length
  {
    return Err(pyo3::exceptions::PyValueError::new_err("attempt batch length mismatch"));
  }
  let mut result = Vec::with_capacity(length);
  for index in 0..length {
    result.push(Py::new(py, OrderAttemptRecord {
      attempt_id: attempt_ids[index].clone(),
      order_id: order_ids[index].clone(),
      revision: revisions[index],
      timestamp: timestamps[index].clone_ref(py),
      market_timestamp: market_timestamps[index].clone_ref(py),
      order: orders[index].clone_ref(py),
    })?);
  }
  Ok(result)
}

#[pyclass(unsendable)]
pub struct OrderCore {
  quantity: f64,
  filled: f64,
  status: i32,
  average_price: f64,
}

#[pymethods]
impl OrderCore {
  #[new]
  fn new(quantity: f64) -> Self {
    Self { quantity: quantity.abs(), filled: 0.0, status: 0, average_price: 0.0 }
  }

  fn apply_fill(&mut self, quantity: f64, price: f64) -> f64 {
    if self.status != 0 && self.status != 4 {
      return 0.0;
    }
    let remaining = (self.quantity - self.filled).max(0.0);
    let fill = quantity.abs().min(remaining);
    if fill > 0.0 {
      let total = self.average_price * self.filled + price * fill;
      self.filled += fill;
      self.average_price = total / self.filled;
      if self.filled >= self.quantity - 1e-12 {
        self.filled = self.quantity;
        self.status = 1;
      } else {
        self.status = 4;
      }
    }
    fill
  }

  fn cancel(&mut self) { if self.status == 0 { self.status = 2; } }
  fn reject(&mut self) { if self.status == 0 { self.status = 3; } }

  #[getter]
  fn quantity(&self) -> f64 { self.quantity }
  #[getter]
  fn filled(&self) -> f64 { self.filled }
  #[getter]
  fn remaining(&self) -> f64 { (self.quantity - self.filled).max(0.0) }
  #[getter]
  fn status(&self) -> i32 { self.status }
  #[getter]
  fn average_price(&self) -> f64 { self.average_price }
}

#[pyclass(unsendable)]
pub struct LedgerAccount {
  cash: f64,
  positions: std::collections::HashMap<String, (f64, f64)>,
}

#[pymethods]
impl LedgerAccount {
  #[new]
  fn new(cash: f64) -> Self {
    Self { cash, positions: std::collections::HashMap::new() }
  }

  fn apply_fill(
    &mut self, product: &str, quantity: f64, price: f64,
    multiplier: f64, fee: f64,
  ) -> f64 {
    let (prior_quantity, prior_cost) = self.positions
      .get(product).copied().unwrap_or((0.0, 0.0));
    let new_quantity = prior_quantity + quantity;
    let epsilon = 1e-12;
    let mut realized = 0.0;
    let mut new_cost = prior_cost;
    if prior_quantity == 0.0 || (prior_quantity > 0.0) == (quantity > 0.0) {
      new_cost = if new_quantity.abs() <= epsilon {
        0.0
      } else {
        (prior_quantity * prior_cost + quantity * price) / new_quantity
      };
    } else {
      let close_abs = prior_quantity.abs().min(quantity.abs());
      realized = close_abs * (price - prior_cost) * prior_quantity.signum() * multiplier;
      if new_quantity.abs() <= epsilon {
        new_cost = 0.0;
      } else if quantity.abs() > prior_quantity.abs() {
        new_cost = price;
      }
    }
    let quantity = if new_quantity.abs() <= epsilon { 0.0 } else { new_quantity };
    self.positions.insert(product.to_string(), (quantity, new_cost));
    self.cash += realized - fee;
    realized
  }

  fn apply_fill_batch(
    &mut self, product: &str,
    quantities: numpy::PyReadonlyArray1<'_, f64>,
    prices: numpy::PyReadonlyArray1<'_, f64>,
    multipliers: numpy::PyReadonlyArray1<'_, f64>,
    fees: numpy::PyReadonlyArray1<'_, f64>,
  ) -> PyResult<(Vec<f64>, Vec<f64>, Vec<f64>)> {
    let quantities = quantities.as_slice()?;
    let prices = prices.as_slice()?;
    let multipliers = multipliers.as_slice()?;
    let fees = fees.as_slice()?;
    let length = quantities.len();
    if prices.len() != length || multipliers.len() != length || fees.len() != length {
      return Err(pyo3::exceptions::PyValueError::new_err("fill batch length mismatch"));
    }
    let (mut prior_quantity, mut prior_cost) = self.positions
      .get(product).copied().unwrap_or((0.0, 0.0));
    let epsilon = 1e-12;
    let mut realized = Vec::with_capacity(length);
    let mut ended_quantity = Vec::with_capacity(length);
    let mut ended_cost = Vec::with_capacity(length);
    for index in 0..length {
      let quantity = quantities[index];
      let price = prices[index];
      let new_quantity = prior_quantity + quantity;
      let mut pnl = 0.0;
      let mut new_cost = prior_cost;
      if prior_quantity == 0.0 || (prior_quantity > 0.0) == (quantity > 0.0) {
        new_cost = if new_quantity.abs() <= epsilon {
          0.0
        } else {
          (prior_quantity * prior_cost + quantity * price) / new_quantity
        };
      } else {
        let close_abs = prior_quantity.abs().min(quantity.abs());
        pnl = close_abs * (price - prior_cost) * prior_quantity.signum() * multipliers[index];
        if new_quantity.abs() <= epsilon {
          new_cost = 0.0;
        } else if quantity.abs() > prior_quantity.abs() {
          new_cost = price;
        }
      }
      prior_quantity = if new_quantity.abs() <= epsilon { 0.0 } else { new_quantity };
      prior_cost = new_cost;
      self.cash += pnl - fees[index];
      realized.push(pnl);
      ended_quantity.push(prior_quantity);
      ended_cost.push(prior_cost);
    }
    self.positions.insert(product.to_string(), (prior_quantity, prior_cost));
    Ok((realized, ended_quantity, ended_cost))
  }

  fn position(&self, product: &str) -> (f64, f64) {
    self.positions.get(product).copied().unwrap_or((0.0, 0.0))
  }

  #[getter]
  fn cash(&self) -> f64 { self.cash }
}

#[pyclass(unsendable)]
pub struct MarketDataMatrix {
  timestamps: Vec<i64>,
  values: Vec<f64>,
  rows: usize,
  columns: usize,
  labels: Vec<Py<PyAny>>,
}

#[pymethods]
impl MarketDataMatrix {
  #[new]
  fn new(
    py: Python<'_>,
    timestamps: numpy::PyReadonlyArray1<'_, i64>,
    values: numpy::PyReadonlyArray2<'_, f64>,
    labels: Vec<Py<PyAny>>,
  ) -> PyResult<Self> {
    let timestamps = timestamps.as_slice()?.to_vec();
    let array = values.as_array();
    let (rows, columns) = array.dim();
    if labels.len() != columns {
      return Err(pyo3::exceptions::PyValueError::new_err("label count mismatch"));
    }
    let values = array.iter().copied().collect::<Vec<f64>>();
    Ok(Self { timestamps, values, rows, columns, labels })
  }

  fn row_at(&self, py: Python<'_>, timestamp: i64, asof: bool) -> PyResult<Py<PyAny>> {
    let dict = pyo3::types::PyDict::new(py);
    let position = if asof {
      match self.timestamps.binary_search(&timestamp) {
        Ok(index) => index as isize,
        Err(0) => -1,
        Err(index) => index as isize - 1,
      }
    } else {
      match self.timestamps.binary_search(&timestamp) {
        Ok(index) => index as isize,
        Err(_) => -1,
      }
    };
    if position < 0 || position as usize >= self.rows {
      return Ok(dict.into());
    }
    let row = position as usize;
    for column in 0..self.columns {
      let value = self.values[row * self.columns + column];
      if !value.is_nan() {
        dict.set_item(self.labels[column].clone_ref(py), value)?;
      }
    }
    Ok(dict.into())
  }

  #[getter]
  fn rows(&self) -> usize { self.rows }

  #[getter]
  fn columns(&self) -> usize { self.columns }
}

#[pyclass(unsendable)]
pub struct EventHeap {
  heap: std::cell::RefCell<std::collections::BinaryHeap<std::cmp::Reverse<EventHeapEntry>>>,
  counter: std::cell::Cell<u64>,
}

struct EventHeapEntry {
  timestamp: i64,
  kind: i32,
  sequence: i32,
  counter: u64,
  payload: Py<PyAny>,
}

impl PartialEq for EventHeapEntry {
  fn eq(&self, other: &Self) -> bool {
    (self.timestamp, self.kind, self.sequence, self.counter)
      == (other.timestamp, other.kind, other.sequence, other.counter)
  }
}
impl Eq for EventHeapEntry {}
impl PartialOrd for EventHeapEntry {
  fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
    Some(self.cmp(other))
  }
}
impl Ord for EventHeapEntry {
  fn cmp(&self, other: &Self) -> std::cmp::Ordering {
    (self.timestamp, self.kind, self.sequence, self.counter)
      .cmp(&(other.timestamp, other.kind, other.sequence, other.counter))
  }
}

#[pymethods]
impl EventHeap {
  #[new]
  fn new() -> Self {
    Self {
      heap: std::cell::RefCell::new(std::collections::BinaryHeap::new()),
      counter: std::cell::Cell::new(0),
    }
  }

  fn push(&self, timestamp: i64, kind: i32, sequence: i32, payload: Py<PyAny>) {
    let counter = self.counter.get();
    self.counter.set(counter + 1);
    self.heap.borrow_mut().push(std::cmp::Reverse(EventHeapEntry {
      timestamp, kind, sequence, counter, payload,
    }));
  }

  fn push_with_counter(&self, timestamp: i64, kind: i32, sequence: i32, counter: u64, payload: Py<PyAny>) {
    self.heap.borrow_mut().push(std::cmp::Reverse(EventHeapEntry {
      timestamp, kind, sequence, counter, payload,
    }));
    if counter >= self.counter.get() {
      self.counter.set(counter + 1);
    }
  }

  fn pop(&self, py: Python<'_>) -> Option<(i64, i32, i32, u64, Py<PyAny>)> {
    self.heap.borrow_mut().pop().map(|std::cmp::Reverse(entry)| {
      (entry.timestamp, entry.kind, entry.sequence, entry.counter, entry.payload.clone_ref(py))
    })
  }

  fn pop_batch(&self, py: Python<'_>) -> Option<(i32, Vec<Py<PyAny>>)> {
    let first = self.pop(py)?;
    let (first_ts, first_kind, _sequence, _counter, first_payload) = first;
    let mut batch = vec![first_payload];
    loop {
      let same = self.heap.borrow().peek().map(|std::cmp::Reverse(entry)| {
        entry.timestamp == first_ts && entry.kind == first_kind
      }).unwrap_or(false);
      if !same {
        break;
      }
      let next = self.pop(py)?;
      batch.push(next.4);
    }
    Some((first_kind, batch))
  }

  fn peek_key(&self) -> Option<(i64, i32, i32, u64)> {
    self.heap.borrow().peek().map(|std::cmp::Reverse(entry)| {
      (entry.timestamp, entry.kind, entry.sequence, entry.counter)
    })
  }

  #[getter]
  fn len(&self) -> usize {
    self.heap.borrow().len()
  }

  fn run(&self, py: Python<'_>, callback: &Bound<'_, PyAny>) -> PyResult<()> {
    use pyo3::types::PyList;
    loop {
      let entry = {
        let batch = self.pop_batch(py);
        batch
      };
      let Some((kind, items)) = entry else { break };
      let list = PyList::new(py, items)?;
      callback.call1((kind, list))?;
    }
    Ok(())
  }
}

#[pyclass]
struct IntervalPairState {
  inner: alpha_algo::PairIntervalState,
}

#[pymethods]
impl IntervalPairState {
  #[new]
  #[pyo3(signature = (correlation=false))]
  fn new(correlation: bool) -> Self {
    Self { inner: alpha_algo::PairIntervalState::new(correlation) }
  }

  fn update(&mut self, start_index: u64, end_index: u64, x: f64, y: f64) -> f64 {
    self.inner.update(start_index, end_index, x, y)
  }
}

fn plan_linreg(values: &[f64], window: usize, metric: &str, min: usize, prop: bool) -> Vec<f64> {
  let window = window.max(1);
  let mut out = vec![f64::NAN; values.len()];
  let (mut sx, mut sy, mut sxx, mut syy, mut sxy) = (0.0f64, 0.0f64, 0.0f64, 0.0f64, 0.0f64);
  let mut count = 0usize;
  for index in 0..values.len() {
    let x = index as f64;
    let y = values[index];
    if y.is_finite() {
      sx += x; sy += y; sxx += x * x; syy += y * y; sxy += x * y; count += 1;
    }
    if index >= window {
      let old_index = index - window;
      let old_x = old_index as f64;
      let old_y = values[old_index];
      if old_y.is_finite() {
        sx -= old_x; sy -= old_y; sxx -= old_x * old_x;
        syy -= old_y * old_y; sxy -= old_x * old_y; count -= 1;
      }
    }
    let width = (index + 1).min(window);
    if count < min.max(3) || (prop && count < width) { continue; }
    let n = count as f64;
    let cxx = sxx - sx * sx / n;
    if cxx <= 0.0 { continue; }
    let cyy = syy - sy * sy / n;
    let cxy = sxy - sx * sy / n;
    let slope = cxy / cxx;
    let intercept = (sy - slope * sx) / n;
    let sse = (syy - intercept * sy - slope * sxy).max(0.0);
    out[index] = match metric {
      "linreg_slope" => slope,
      "linreg_r2" => if cyy <= 0.0 { f64::NAN } else { 1.0 - sse / cyy },
      "linreg_resid_std" => if count < 3 { f64::NAN } else { (sse / (n - 2.0)).sqrt() },
      "linreg_tstat" => {
        if count < 3 { f64::NAN } else {
          let se = ((sse / (n - 2.0)) / cxx).sqrt();
          if se > 0.0 { slope / se } else { f64::NAN }
        }
      }
      _ => f64::NAN,
    };
  }
  out
}

#[pyclass]
struct FactorPlanState {
  inner: alpha_algo::FactorPlanKernel,
}

#[pymethods]
impl FactorPlanState {
  #[new]
  #[pyo3(signature = (json, products))]
  fn new(json: &str, products: usize) -> PyResult<Self> {
    Ok(Self {
      inner: alpha_algo::FactorPlanKernel::from_spec_json(json, products)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?,
    })
  }

  fn update(&mut self, py: Python<'_>, values: numpy::PyReadonlyArray1<f64>) -> PyResult<Py<numpy::PyArray1<f64>>> {
    use numpy::IntoPyArray;
    Ok(self.inner.update(values.as_slice()?)
      .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?
      .into_pyarray(py).unbind())
  }
}

#[pyclass]
struct IntervalState {
  inner: alpha_algo::IntervalKernel,
}

#[pymethods]
impl IntervalState {
  #[new]
  #[pyo3(signature = (op="mean", quantile=None, min_periods=1, propagate_nan=false))]
  fn new(op: &str, quantile: Option<f64>, min_periods: usize, propagate_nan: bool) -> PyResult<Self> {
    use alpha_algo::SessionOp;
    let op = match op {
      "sum" => SessionOp::Sum, "mean" => SessionOp::Mean,
      "var" => SessionOp::Var, "std" => SessionOp::Std,
      "min" => SessionOp::Min, "max" => SessionOp::Max,
      "skew" => SessionOp::Skew, "argmin" => SessionOp::Argmin,
      "argmax" => SessionOp::Argmax, "rank" => SessionOp::Rank,
      "mad" => SessionOp::Mad,
      "median" | "quantile" => SessionOp::Quantile(quantile.unwrap_or(0.5)),
      other => return Err(pyo3::exceptions::PyValueError::new_err(
        format!("unsupported interval op: {other}")
      )),
    };
    let inner = alpha_algo::SessionWindowState::new_explicit(op)
      .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?
      .with_semantics(min_periods, propagate_nan);
    Ok(Self { inner })
  }

  fn update(&mut self, start_index: u64, end_index: u64, value: f64) -> f64 {
    self.inner.update_explicit(start_index, end_index, value)
  }
}

#[pyclass]
struct EmaState {
  inner: alpha_algo::EmaState,
}

#[pymethods]
impl EmaState {
  #[new]
  #[pyo3(signature = (span, min_periods=1, propagate_nan=true))]
  fn new(span: usize, min_periods: usize, propagate_nan: bool) -> PyResult<Self> {
    let inner = alpha_algo::EmaState::new(span)
      .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?
      .with_semantics(min_periods, propagate_nan);
    Ok(Self { inner })
  }

  fn update(&mut self, value: f64) -> f64 { self.inner.update(value) }
}

#[pymodule]
fn _algo(m: &Bound<'_, PyModule>) -> PyResult<()> {
  use algo_impl::*;

  pyo3_log::init();

  m.add_function(wrap_pyfunction!(ema, m)?)?;
  m.add_function(wrap_pyfunction!(interval_ema, m)?)?;
  m.add_function(wrap_pyfunction!(bar_since, m)?)?;
  m.add_function(wrap_pyfunction!(cross_sectional, m)?)?;
  m.add_function(wrap_pyfunction!(interval_rolling, m)?)?;
  m.add_function(wrap_pyfunction!(interval_rolling_pair, m)?)?;
  m.add_function(wrap_pyfunction!(session_rolling_sum, m)?)?;
  m.add_function(wrap_pyfunction!(session_rolling_mean, m)?)?;
  m.add_function(wrap_pyfunction!(set_ctx, m)?)?;
  m.add_class::<EventHeap>()?;
  m.add_class::<MarketDataMatrix>()?;
  m.add_class::<LedgerAccount>()?;
  m.add_class::<OrderCore>()?;
  m.add_class::<OrderAttemptRecord>()?;
  m.add_function(wrap_pyfunction!(create_attempt_records, m)?)?;
  m.add_class::<VectorBacktest>()?;
  m.add_class::<FeeModel>()?;
  m.add_class::<TargetAllocator>()?;
  m.add_class::<OrderLifecycleBatch>()?;
  m.add_class::<OrderConstructionKernel>()?;
  m.add_class::<ThresholdKernel>()?;
  m.add_class::<EmaState>()?;
  m.add_class::<IntervalState>()?;
  m.add_class::<FactorPlanState>()?;
  m.add_class::<IntervalPairState>()?;
  m.add_class::<BatchPlan>()?;
  m.add_class::<GroupKernel>()?;
  m.add_class::<TermCarryKernel>()?;
  m.add_class::<LifecycleKernel>()?;
#[pyclass(unsendable)]
pub struct PanelPlanStream {
  ops: Vec<f64>,
  params: Vec<f64>,
  aux: Vec<f64>,
  slot_count: usize,
  leaf_count: usize,
  output_slot: usize,
  product_count: usize,
  tiebreak: Vec<f64>,
  values: Vec<Vec<f64>>,
  histories: Vec<Vec<std::collections::VecDeque<f64>>>,
}

#[pymethods]
impl PanelPlanStream {
  #[new]
  fn new(
    ops: Vec<f64>, params: Vec<f64>, aux: Vec<f64>,
    slot_count: usize, leaf_count: usize, output_slot: usize,
    product_count: usize,
    tiebreak: Vec<f64>,
  ) -> Self {
    let history_count = ops.len().div_ceil(8);
    Self {
      ops, params, aux, slot_count, leaf_count, output_slot, product_count, tiebreak,
      values: vec![vec![f64::NAN; slot_count]; product_count],
      histories: vec![vec![std::collections::VecDeque::new(); history_count]; product_count],
    }
  }

  fn on_bar(&mut self, leaves: Vec<Vec<f64>>) -> PyResult<Vec<f64>> {
    if leaves.len() != self.product_count {
      return Err(pyo3::exceptions::PyValueError::new_err("panel product count mismatch"));
    }
    for product in 0..self.product_count {
      if leaves[product].len() != self.leaf_count {
        return Err(pyo3::exceptions::PyValueError::new_err("panel leaf count mismatch"));
      }
      for index in 0..self.leaf_count {
        self.values[product][index] = leaves[product][index];
      }
    }
    let op_count = self.ops.len() / 8;
    for op in 0..op_count {
      let base = op * 8;
      let code = self.ops[base] as usize;
      let out = self.ops[base + 1] as usize;
      let slot = |position: usize| -> Option<usize> {
        let value = self.ops[base + position];
        if value < 0.0 { None } else { Some(value as usize) }
      };
      let a = slot(2);
      let b = slot(3);
      let pbase = op * 8;
      let window = self.params[pbase] as usize;
      let min_count = self.params[pbase + 1] as usize;
      let periods = self.params[pbase + 3] as i64;
      if (75..=77).contains(&code) {
        let signal_slot = a.ok_or_else(|| pyo3::exceptions::PyValueError::new_err("residualize signal missing"))?;
        let exposure_count = code - 74;
        let exposure_slots = [b, slot(4), slot(5)];
        for product in 0..self.product_count {
          self.values[product][out] = f64::NAN;
        }
        let mask_slot_raw = self.ops[base + 6];
        let mask_slot = if mask_slot_raw < 0.0 { None } else { Some(mask_slot_raw as usize) };
        let mut ys: Vec<f64> = Vec::new();
        let mut rows_x: Vec<[f64; 3]> = Vec::new();
        let mut positions: Vec<usize> = Vec::new();
        for product in 0..self.product_count {
          let signal = self.values[product][signal_slot];
          let eligible = mask_slot.map(|slot| self.values[product][slot] > 0.0).unwrap_or(true);
          if !eligible || !signal.is_finite() { continue; }
          let mut row = [0.0f64; 3];
          let mut ok = true;
          for e in 0..exposure_count {
            let Some(slot) = exposure_slots[e] else { ok = false; break; };
            let value = self.values[product][slot];
            if !value.is_finite() { ok = false; break; }
            row[e] = value;
          }
          if !ok { continue; }
          ys.push(signal);
          rows_x.push(row);
          positions.push(product);
        }
        let k = exposure_count;
        if ys.len() <= k + 1 { continue; }
        let size = k + 1;
        let mut xtx = vec![vec![0.0f64; size]; size];
        let mut xty = vec![0.0f64; size];
        for (index, y) in ys.iter().enumerate() {
          let mut row = [0.0f64; 4];
          row[0] = 1.0;
          for j in 0..k { row[j + 1] = rows_x[index][j]; }
          for a_index in 0..size {
            xty[a_index] += row[a_index] * y;
            for b_index in 0..size {
              xtx[a_index][b_index] += row[a_index] * row[b_index];
            }
          }
        }
        let mut singular = false;
        for col in 0..size {
          let mut pivot = col;
          for row in col + 1..size {
            if xtx[row][col].abs() > xtx[pivot][col].abs() { pivot = row; }
          }
          if !(xtx[pivot][col].abs() > 1e-18) { singular = true; break; }
          xtx.swap(col, pivot);
          xty.swap(col, pivot);
          let diag = xtx[col][col];
          for b_index in col..size { xtx[col][b_index] /= diag; }
          xty[col] /= diag;
          for row in 0..size {
            if row == col { continue; }
            let factor = xtx[row][col];
            for b_index in col..size { xtx[row][b_index] -= factor * xtx[col][b_index]; }
            xty[row] -= factor * xty[col];
          }
        }
        if singular { continue; }
        for (index, product) in positions.iter().enumerate() {
          let mut fitted = xty[0];
          for j in 0..k { fitted += xty[j + 1] * rows_x[index][j]; }
          self.values[*product][out] = ys[index] - fitted;
        }
        continue;
      }
      if code == 74 {
        let input = a.ok_or_else(|| pyo3::exceptions::PyValueError::new_err("group input missing"))?;
        let mask_slot = b.ok_or_else(|| pyo3::exceptions::PyValueError::new_err("group mask missing"))?;
        let aux_offset = self.params[pbase + 6] as usize;
        let aux_len = self.params[pbase + 7] as usize;
        let category = &self.aux[aux_offset..aux_offset + aux_len];
        let operation = self.params[pbase] as usize;
        for product in 0..self.product_count {
          self.values[product][out] = f64::NAN;
        }
        let max_id = category.iter()
          .map(|value| if value.is_finite() && *value >= 0.0 { *value as usize } else { 0 })
          .max().unwrap_or(0);
        for id in 0..=max_id {
          let mut values: Vec<f64> = Vec::new();
          let mut positions: Vec<usize> = Vec::new();
          for product in 0..self.product_count {
            if product >= category.len() { continue; }
            let category_id = if category[product].is_finite() && category[product] >= 0.0 {
              category[product] as usize
            } else { usize::MAX };
            if category_id != id { continue; }
            let value = self.values[product][input];
            let mask = self.values[product][mask_slot];
            if !(value.is_finite() && mask.is_finite() && mask > 0.0) { continue; }
            values.push(value);
            positions.push(product);
          }
          if values.is_empty() { continue; }
          let count = values.len();
          if operation == 0 {
            let mut order: Vec<usize> = (0..count).collect();
            order.sort_by(|left, right| values[*left].partial_cmp(&values[*right]).unwrap_or(std::cmp::Ordering::Equal));
            let mut index = 0usize;
            while index < order.len() {
              let mut end = index + 1;
              while end < order.len() && values[order[end]] == values[order[index]] { end += 1; }
              let rank = ((index + 1) as f64 + end as f64) / 2.0;
              for position in index..end {
                self.values[positions[order[position]]][out] = rank / count as f64 - 0.5;
              }
              index = end;
            }
          } else if operation == 1 {
            if count < 2 { continue; }
            let mean = values.iter().sum::<f64>() / count as f64;
            let variance = values.iter().map(|value| { let d = value - mean; d * d }).sum::<f64>() / (count - 1) as f64;
            let std = variance.sqrt();
            if std.is_nan() { continue; }
            for (position, value) in positions.iter().zip(values.iter()) {
              self.values[*position][out] = if std > 0.0 { (value - mean) / std } else { 0.0 };
            }
          } else {
            let mean = values.iter().sum::<f64>() / count as f64;
            for (position, value) in positions.iter().zip(values.iter()) {
              self.values[*position][out] = value - mean;
            }
          }
        }
        continue;
      }
      if code == 73 {
        let input = a.ok_or_else(|| pyo3::exceptions::PyValueError::new_err("ordinal input missing"))?;
        let mask_slot = b.ok_or_else(|| pyo3::exceptions::PyValueError::new_err("ordinal mask missing"))?;
        let ascending = self.params[pbase] != 0.0;
        let mut eligible: Vec<usize> = Vec::new();
        for product in 0..self.product_count {
          let value = self.values[product][input];
          let mask = self.values[product][mask_slot];
          if value.is_finite() && mask.is_finite() && mask > 0.0 {
            eligible.push(product);
          }
        }
        for product in 0..self.product_count {
          self.values[product][out] = f64::NAN;
        }
        eligible.sort_by(|left, right| {
          let left_value = self.values[*left][input];
          let right_value = self.values[*right][input];
          let base = left_value.partial_cmp(&right_value).unwrap_or(std::cmp::Ordering::Equal);
          let base = if ascending { base } else { base.reverse() };
          if base == std::cmp::Ordering::Equal {
            self.tiebreak[*left].partial_cmp(&self.tiebreak[*right]).unwrap_or(std::cmp::Ordering::Equal)
          } else {
            base
          }
        });
        for (position, product) in eligible.iter().enumerate() {
          self.values[*product][out] = (position + 1) as f64;
        }
        continue;
      }
      if code == 70 || code == 71 || code == 72 {
        let input = a.ok_or_else(|| pyo3::exceptions::PyValueError::new_err("cross input missing"))?;
        let mask = if code == 71 {
          Some(b.ok_or_else(|| pyo3::exceptions::PyValueError::new_err("cross mask missing"))?)
        } else { None };
        let mut entries: Vec<(usize, f64)> = Vec::new();
        for product in 0..self.product_count {
          let value = self.values[product][input];
          if !value.is_finite() { continue; }
          if let Some(mask_slot) = mask {
            let eligible = self.values[product][mask_slot];
            if !(eligible.is_finite() && eligible > 0.0) { continue; }
          }
          entries.push((product, value));
        }
        for product in 0..self.product_count {
          self.values[product][out] = f64::NAN;
        }
        if entries.is_empty() { continue; }
        if code == 72 {
          let count = entries.len();
          let mean = entries.iter().map(|(_, value)| *value).sum::<f64>() / count as f64;
          if count < 2 { continue; }
          let variance = entries.iter()
            .map(|(_, value)| { let d = value - mean; d * d })
            .sum::<f64>() / (count - 1) as f64;
          let std = variance.sqrt();
          if !std.is_finite() || std == 0.0 { continue; }
          for (product, value) in entries.iter() {
            self.values[*product][out] = (value - mean) / std;
          }
          continue;
        }
        let mut order: Vec<usize> = (0..entries.len()).collect();
        order.sort_by(|left, right| {
          entries[*left].1.partial_cmp(&entries[*right].1).unwrap_or(std::cmp::Ordering::Equal)
        });
        let count = entries.len() as f64;
        let mut index = 0usize;
        while index < order.len() {
          let mut end = index + 1;
          while end < order.len() && entries[order[end]].1 == entries[order[index]].1 {
            end += 1;
          }
          let rank = ((index + 1) as f64 + end as f64) / 2.0;
          for position in index..end {
            let product = entries[order[position]].0;
            self.values[product][out] = rank / count - 0.5;
          }
          index = end;
        }
        continue;
      }
      for product in 0..self.product_count {
        if code == 2 {
          self.values[product][out] = self.params[pbase + 4];
        } else if code == 1 {
          let input = a.ok_or_else(|| pyo3::exceptions::PyValueError::new_err("shift input missing"))?;
          let history = &mut self.histories[product][op];
          history.push_back(self.values[product][input]);
          let keep = periods.max(0) as usize + 1;
          while history.len() > keep { history.pop_front(); }
          self.values[product][out] = if periods >= 0 && history.len() > periods as usize {
            history[0]
          } else { f64::NAN };
        } else if (10..=17).contains(&code) {
          let input = a.ok_or_else(|| pyo3::exceptions::PyValueError::new_err("unary input missing"))?;
          self.values[product][out] = plan_unary_value(code, self.values[product][input]);
        } else if (20..=26).contains(&code) || (100..=107).contains(&code) {
          let left = a.map(|index| self.values[product][index]).unwrap_or(self.params[pbase + 4]);
          let right = b.map(|index| self.values[product][index]).unwrap_or(self.params[pbase + 5]);
          self.values[product][out] = plan_binary_value(code, left, right);
        } else if code == 90 {
          let input_count = self.params[pbase + 4] as usize;
          let node_count = self.params[pbase + 5] as usize;
          let offset = self.params[pbase + 6] as usize;
          let length = self.params[pbase + 7] as usize;
          let program = &self.aux[offset..offset + length];
          let mut inputs: Vec<f64> = Vec::with_capacity(input_count);
          for index in 0..input_count {
            let raw = program[2 * index];
            inputs.push(if raw < 0.0 { program[2 * index + 1] } else { self.values[product][raw as usize] });
          }
          let nodes_base = 2 * input_count;
          let mut registers = vec![f64::NAN; node_count];
          for node in 0..node_count {
            let row = nodes_base + 4 * node;
            let node_code = program[row] as usize;
            let src1 = program[row + 2] as usize;
            let src2 = program[row + 3] as usize;
            let resolve = |source: usize| -> f64 {
              if source < input_count { inputs[source] } else { registers[source - input_count] }
            };
            let left = resolve(src1);
            let right = resolve(src2);
            registers[node] = if (10..=17).contains(&node_code) {
              plan_unary_value(node_code, left)
            } else {
              plan_binary_value(node_code, left, right)
            };
          }
          self.values[product][out] = registers[node_count - 1];
        } else if (30..=35).contains(&code) {
          let input = a.ok_or_else(|| pyo3::exceptions::PyValueError::new_err("rolling input missing"))?;
          let raw = self.values[product][input];
          let history = &mut self.histories[product][op];
          history.push_back(raw);
          while history.len() > window { history.pop_front(); }
          let finite: Vec<f64> = history.iter().copied().filter(|value| value.is_finite()).collect();
          self.values[product][out] = if finite.len() < min_count { f64::NAN } else {
            match code {
              30 => finite.iter().sum::<f64>() / finite.len() as f64,
              31 | 32 => {
                if finite.len() < 2 { f64::NAN } else {
                  let mean = finite.iter().sum::<f64>() / finite.len() as f64;
                  let variance = finite.iter().map(|value| (value - mean) * (value - mean)).sum::<f64>()
                    / (finite.len() - 1) as f64;
                  if code == 31 { variance.sqrt() } else { variance }
                }
              }
              33 => finite.iter().copied().fold(f64::INFINITY, f64::min),
              34 => finite.iter().copied().fold(f64::NEG_INFINITY, f64::max),
              _ => finite.iter().sum::<f64>(),
            }
          };
        } else {
          return Err(pyo3::exceptions::PyValueError::new_err(format!("unsupported panel plan op {code}")));
        }
      }
    }
    Ok((0..self.product_count).map(|product| self.values[product][self.output_slot]).collect())
  }
}

#[pyclass(unsendable)]
pub struct PlanStream {
  ops: Vec<f64>,
  params: Vec<f64>,
  aux: Vec<f64>,
  slot_count: usize,
  leaf_count: usize,
  output_slot: usize,
  values: Vec<f64>,
  histories: Vec<std::collections::VecDeque<f64>>,
}

fn plan_binary_value(code: usize, a: f64, b: f64) -> f64 {
  match code {
    20 => a + b, 21 => a - b, 22 => a * b, 23 => a / b, 24 => a.powf(b),
    25 => if a.is_nan() || b.is_nan() { f64::NAN } else { a.max(b) },
    26 => if a.is_nan() || b.is_nan() { f64::NAN } else { a.min(b) },
    100 => if a > b { 1.0 } else { 0.0 },
    101 => if a < b { 1.0 } else { 0.0 },
    102 => if a >= b { 1.0 } else { 0.0 },
    103 => if a <= b { 1.0 } else { 0.0 },
    104 => if a == b { 1.0 } else { 0.0 },
    105 => if a != b { 1.0 } else { 0.0 },
    106 => if a != 0.0 && b != 0.0 { 1.0 } else { 0.0 },
    107 => if a != 0.0 || b != 0.0 { 1.0 } else { 0.0 },
    _ => f64::NAN,
  }
}

fn plan_unary_value(code: usize, value: f64) -> f64 {
  match code {
    10 => -value, 11 => value.abs(), 12 => value.ln(), 13 => value.sqrt(),
    14 => value.tanh(), 15 => value.exp(),
    16 => if value.is_nan() { f64::NAN } else if value > 0.0 { 1.0 } else if value < 0.0 { -1.0 } else { 0.0 },
    17 => if value == 0.0 { 1.0 } else { 0.0 },
    _ => f64::NAN,
  }
}

#[pymethods]
impl PlanStream {
  #[new]
  fn new(
    ops: Vec<f64>, params: Vec<f64>, aux: Vec<f64>,
    slot_count: usize, leaf_count: usize, output_slot: usize,
  ) -> Self {
    let history_count = ops.len().div_ceil(8);
    Self {
      ops, params, aux, slot_count, leaf_count, output_slot,
      values: vec![f64::NAN; slot_count],
      histories: vec![std::collections::VecDeque::new(); history_count],
    }
  }

  fn on_bar(&mut self, leaves: Vec<f64>) -> PyResult<f64> {
    if leaves.len() != self.leaf_count { return Err(pyo3::exceptions::PyValueError::new_err("leaf count mismatch")); }
    for index in 0..self.leaf_count { self.values[index] = leaves[index]; }
    let op_count = self.ops.len() / 8;
    for op in 0..op_count {
      let base = op * 8;
      let code = self.ops[base] as usize;
      let out = self.ops[base + 1] as usize;
      let slot = |position: usize| -> Option<usize> {
        let value = self.ops[base + position];
        if value < 0.0 { None } else { Some(value as usize) }
      };
      let a = slot(2); let b = slot(3); let c = slot(4); let d = slot(5); let e = slot(6);
      let pbase = op * 8;
      let window = self.params[pbase] as usize;
      let min_count = self.params[pbase + 1] as usize;
      let periods = self.params[pbase + 3] as i64;
      if code == 2 {
        self.values[out] = self.params[pbase + 4];
      } else if code == 1 {
        let input = a.ok_or_else(|| pyo3::exceptions::PyValueError::new_err("shift input missing"))?;
        let history = &mut self.histories[op];
        history.push_back(self.values[input]);
        let keep = periods.max(0) as usize + 1;
        while history.len() > keep { history.pop_front(); }
        self.values[out] = if periods >= 0 && history.len() > periods as usize { history[0] } else { f64::NAN };
      } else if (10..=17).contains(&code) {
        let input = a.ok_or_else(|| pyo3::exceptions::PyValueError::new_err("unary input missing"))?;
        self.values[out] = plan_unary_value(code, self.values[input]);
      } else if (20..=26).contains(&code) || (100..=107).contains(&code) {
        let left = a.map(|index| self.values[index]).unwrap_or(self.params[pbase + 4]);
        let right = b.map(|index| self.values[index]).unwrap_or(self.params[pbase + 5]);
        self.values[out] = plan_binary_value(code, left, right);
      } else if code == 90 {
        let input_count = self.params[pbase + 4] as usize;
        let node_count = self.params[pbase + 5] as usize;
        let offset = self.params[pbase + 6] as usize;
        let length = self.params[pbase + 7] as usize;
        let program = &self.aux[offset..offset + length];
        let mut inputs: Vec<f64> = Vec::with_capacity(input_count);
        for index in 0..input_count {
          let raw = program[2 * index];
          inputs.push(if raw < 0.0 { program[2 * index + 1] } else { self.values[raw as usize] });
        }
        let nodes_base = 2 * input_count;
        let mut registers = vec![f64::NAN; node_count];
        for node in 0..node_count {
          let row = nodes_base + 4 * node;
          let node_code = program[row] as usize;
          let src1 = program[row + 2] as usize;
          let src2 = program[row + 3] as usize;
          let resolve = |source: usize| -> f64 {
            if source < input_count { inputs[source] } else { registers[source - input_count] }
          };
          let left = resolve(src1);
          let right = resolve(src2);
          registers[node] = if (10..=17).contains(&node_code) {
            plan_unary_value(node_code, left)
          } else {
            plan_binary_value(node_code, left, right)
          };
        }
        self.values[out] = registers[node_count - 1];
      } else if (30..=35).contains(&code) {
        let input = a.ok_or_else(|| pyo3::exceptions::PyValueError::new_err("rolling input missing"))?;
        let raw = self.values[input];
        let history = &mut self.histories[op];
        history.push_back(raw);
        while history.len() > window { history.pop_front(); }
        let finite: Vec<f64> = history.iter().copied().filter(|value| value.is_finite()).collect();
        self.values[out] = if finite.len() < min_count { f64::NAN } else {
          match code {
            30 => finite.iter().sum::<f64>() / finite.len() as f64,
            31 | 32 => {
              if finite.len() < 2 { f64::NAN } else {
                let mean = finite.iter().sum::<f64>() / finite.len() as f64;
                let variance = finite.iter().map(|value| (value - mean) * (value - mean)).sum::<f64>()
                  / (finite.len() - 1) as f64;
                if code == 31 { variance.sqrt() } else { variance }
              }
            }
            33 => finite.iter().copied().fold(f64::INFINITY, f64::min),
            34 => finite.iter().copied().fold(f64::NEG_INFINITY, f64::max),
            _ => finite.iter().sum::<f64>(),
          }
        };
      } else {
        return Err(pyo3::exceptions::PyValueError::new_err(format!("unsupported plan op {code}")));
      }
      let _ = (c, d, e);
    }
    Ok(self.values[self.output_slot])
  }
}

  m.add_class::<PlanStream>()?;
  m.add_class::<PanelPlanStream>()?;
  m.add_class::<LongShortKernel>()?;
  m.add_class::<CashConstraintKernel>()?;
  m.add_class::<NativeSession>()?;
  m.add_class::<NativeGroupSession>()?;
  m.add_class::<NativeTraceBuilder>()?;
  m.add_class::<MarginAccount>()?;
  m.add_class::<LedgerState>()?;
  m.add_class::<LotBook>()?;
  register_functions(m)?;
  Ok(())
}
