// Copyright 2026 MSD-RS Project LiJia
// SPDX-License-Identifier: BSD-2-Clause
//
// FactorTester fork additions: scope-partitioned expanding aggregations.
//
// Unlike rolling windows, these reset at a partition boundary (trading day,
// session, every K observed bars). Python computes the partition key per bar;
// the kernel only consumes `keys` and aggregates from the partition start up to
// and including the current bar. NaN is "not observed" and is skipped.

use num_traits::Float;

use crate::algo::{Context, Error, is_normal};

/// Aggregation ids shared with the Python layer.
pub const SCOPE_MEAN: usize = 0;
pub const SCOPE_STD: usize = 1;
pub const SCOPE_VAR: usize = 2;
pub const SCOPE_MIN: usize = 3;
pub const SCOPE_MAX: usize = 4;
pub const SCOPE_SUM: usize = 5;
pub const SCOPE_MEDIAN: usize = 6;
pub const SCOPE_QUANTILE: usize = 7;
pub const SCOPE_ARGMAX: usize = 8;
pub const SCOPE_ARGMIN: usize = 9;

fn median_sorted<NumT: Float>(values: &[NumT]) -> NumT {
  let n = values.len();
  if n % 2 == 1 {
    values[n / 2]
  } else {
    (values[n / 2 - 1] + values[n / 2]) / NumT::from(2).unwrap()
  }
}

/// Scope-partitioned expanding aggregation with `min_count` valid observations.
pub fn ta_ft_scope_agg<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  keys: &[NumT],
  min_count: usize,
  op: usize,
  quantile: NumT,
) -> Result<(), Error> {
  if r.len() != input.len() {
    return Err(Error::LengthMismatch(r.len(), input.len()));
  }
  r.fill(NumT::nan());
  if keys.is_empty() {
    return Ok(());
  }
  let groups = ctx.groups().max(1);
  let rows = input.len() / groups;
  if keys.len() < rows {
    return Err(Error::LengthMismatch(keys.len(), rows));
  }
  let minimum = min_count.max(1);

  for g in 0..groups {
    let base = g * rows;
    let mut current_key = NumT::nan();
    let mut sum = NumT::zero();
    let mut sum_sq = NumT::zero();
    let mut count = 0usize;
    let mut min_value = NumT::nan();
    let mut max_value = NumT::nan();
    let mut min_pos = 0usize;
    let mut max_pos = 0usize;
    let mut values: Vec<NumT> = Vec::with_capacity(rows.min(1024));
    for t in 0..rows {
      let key = keys[t];
      if !(key == current_key) {
        current_key = key;
        sum = NumT::zero();
        sum_sq = NumT::zero();
        count = 0;
        min_value = NumT::nan();
        max_value = NumT::nan();
        values.clear();
      }
      let value = input[base + t];
      if is_normal(&value) {
        sum = sum + value;
        sum_sq = sum_sq + value * value;
        if count == 0 || value < min_value {
          min_value = value;
          min_pos = t;
        }
        if count == 0 || value > max_value {
          max_value = value;
          max_pos = t;
        }
        count += 1;
        values.push(value);
      }
      if count < minimum {
        continue;
      }
      let n = NumT::from(count).unwrap();
      r[base + t] = match op {
        SCOPE_MEAN => sum / n,
        SCOPE_SUM => sum,
        SCOPE_MIN => min_value,
        SCOPE_MAX => max_value,
        SCOPE_VAR => {
          let centered = (sum_sq - sum * sum / n) / (n - NumT::one());
          if centered > NumT::zero() { centered } else { NumT::zero() }
        }
        SCOPE_STD => {
          let centered = (sum_sq - sum * sum / n) / (n - NumT::one());
          if centered > NumT::zero() { centered.sqrt() } else { NumT::zero() }
        }
        SCOPE_MEDIAN => {
          values.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
          median_sorted(&values)
        }
        SCOPE_QUANTILE => {
          values.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
          let position = quantile * NumT::from(count - 1).unwrap();
          let lower = position.floor().to_usize().unwrap_or(0).min(count - 1);
          let upper = (lower + 1).min(count - 1);
          let frac = position - NumT::from(lower).unwrap();
          values[lower] + (values[upper] - values[lower]) * frac
        }
        SCOPE_ARGMAX => NumT::from(max_pos).unwrap(),
        _ => NumT::from(min_pos).unwrap(),
      };
    }
  }
  Ok(())
}
