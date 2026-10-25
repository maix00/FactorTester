// Copyright 2026 MSD-RS Project LiJia
// SPDX-License-Identifier: BSD-2-Clause

use num_traits::Float;
use rayon::prelude::*;

use crate::algo::{is_normal, Context, Error};

pub const TRUNC_MEAN: usize = 0;
pub const TRUNC_STD: usize = 1;
pub const TRUNC_VAR: usize = 2;
pub const TRUNC_MIN: usize = 3;
pub const TRUNC_MAX: usize = 4;
pub const TRUNC_SUM: usize = 5;
pub const TRUNC_MEDIAN: usize = 6;
pub const TRUNC_QUANTILE: usize = 7;
pub const TRUNC_ARGMAX: usize = 8;
pub const TRUNC_ARGMIN: usize = 9;

fn quantile_sorted<NumT: Float>(values: &[NumT], q: NumT) -> NumT {
  if values.is_empty() {
    return NumT::nan();
  }
  let position = q * NumT::from(values.len() - 1).unwrap();
  let lower = position.floor().to_usize().unwrap_or(0).min(values.len() - 1);
  let upper = (lower + 1).min(values.len() - 1);
  let frac = position - NumT::from(lower).unwrap();
  values[lower] + (values[upper] - values[lower]) * frac
}

/// Prefix aggregation inside scope partitions with fixed `[start, end]` truncation.
///
/// `trunc_end < 0` means "up to the current bar". Positions after a fixed end
/// keep the completed window's value, matching pandas expanding semantics.
pub fn ta_ft_scope_trunc<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  keys: &[NumT],
  trunc_start: usize,
  trunc_end: usize,
  min_count: usize,
  op: usize,
  quantile: NumT,
) -> Result<(), Error> {
  let groups = ctx.groups().max(1);
  if input.len() != r.len() || keys.is_empty() {
    return Err(Error::LengthMismatch(input.len(), r.len()));
  }
  let rows = input.len() / groups;
  if keys.len() < rows {
    return Err(Error::LengthMismatch(keys.len(), rows));
  }
  let start = trunc_start;
  let end = if trunc_end == usize::MAX { None } else { Some(trunc_end) };
  let minimum = min_count.max(1);
  r.par_chunks_mut(rows).enumerate().for_each(|(group, out)| {
    let base = group * rows;
    let mut partition_start = 0usize;
    let mut previous_key = NumT::nan();
    for t in 0..rows {
      let key = keys[t];
      if t == 0 || !(key == previous_key) {
        previous_key = key;
        partition_start = t;
      }
      out[t] = NumT::nan();
      let raw = t - partition_start;
      if raw < start {
        continue;
      }
      let stop = match end {
        Some(limit) => raw.min(limit),
        None => raw,
      };
      if stop < start {
        continue;
      }
      let mut values: Vec<NumT> = Vec::with_capacity(stop - start + 1);
      let mut count = 0usize;
      let mut sum = NumT::zero();
      let mut sum_sq = NumT::zero();
      let mut min_value = NumT::nan();
      let mut max_value = NumT::nan();
      let mut min_pos = 0usize;
      let mut max_pos = 0usize;
      for offset in start..=stop {
        let value = input[base + partition_start + offset];
        if !is_normal(&value) {
          continue;
        }
        values.push(value);
        sum = sum + value;
        sum_sq = sum_sq + value * value;
        if count == 0 || value < min_value {
          min_value = value;
          min_pos = offset;
        }
        if count == 0 || value > max_value {
          max_value = value;
          max_pos = offset;
        }
        count += 1;
      }
      if count < minimum {
        continue;
      }
      let n = NumT::from(count).unwrap();
      out[t] = match op {
        TRUNC_MEAN => sum / n,
        TRUNC_SUM => sum,
        TRUNC_MIN => min_value,
        TRUNC_MAX => max_value,
        TRUNC_STD | TRUNC_VAR => {
          if count < 2 {
            NumT::nan()
          } else {
            let variance = (sum_sq - sum * sum / n) / (n - NumT::one());
            let variance = if variance > NumT::zero() { variance } else { NumT::zero() };
            if op == TRUNC_STD { variance.sqrt() } else { variance }
          }
        }
        TRUNC_MEDIAN => {
          values.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
          quantile_sorted(&values, NumT::from(0.5).unwrap())
        }
        TRUNC_QUANTILE => {
          values.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
          quantile_sorted(&values, quantile)
        }
        TRUNC_ARGMAX | TRUNC_ARGMIN => {
          let best = if op == TRUNC_ARGMAX { max_pos } else { min_pos };
          let span = raw.saturating_sub(start);
          if span == 0 {
            NumT::zero()
          } else {
            NumT::from(raw - best).unwrap() / NumT::from(span).unwrap()
          }
        }
        _ => NumT::nan(),
      };
    }
  });
  Ok(())
}
