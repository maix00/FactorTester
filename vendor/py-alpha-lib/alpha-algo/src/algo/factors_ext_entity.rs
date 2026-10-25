// Copyright 2026 MSD-RS Project LiJia
// SPDX-License-Identifier: BSD-2-Clause

use num_traits::Float;
use rayon::prelude::*;

use crate::algo::{is_normal, Context, Error};

pub const GROUP_MEAN: usize = 0;
pub const GROUP_SUM: usize = 1;
pub const GROUP_COUNT: usize = 2;
pub const GROUP_MIN: usize = 3;
pub const GROUP_MAX: usize = 4;
pub const GROUP_WEIGHTED_MEAN: usize = 5;

/// Reduce an ``(entities, rows)`` panel by category.
///
/// The output keeps the input shape; every entity receives the aggregate of its
/// category group. Python selects one representative row per group to obtain a
/// dense ``(groups, rows)`` panel. This matches the existing Lua/Python binding
/// contract while keeping the reduction in Rust.
pub fn ta_ft_group_reduce<NumT: Float + Send + Sync>(
  _ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  category: &[NumT],
  weight: &[NumT],
  op: usize,
) -> Result<(), Error> {
  let entities = category.len();
  if entities == 0 {
    return Ok(());
  }
  if input.len() != r.len() || input.len() % entities != 0 {
    return Err(Error::LengthMismatch(input.len(), category.len()));
  }
  let rows = input.len() / entities;
  if !weight.is_empty() && weight.len() != input.len() {
    return Err(Error::LengthMismatch(weight.len(), input.len()));
  }
  let has_weight = !weight.is_empty();
  let mut groups = 0usize;
  for &cat in category {
    if is_normal(&cat) {
      let value = cat.to_f64().unwrap_or(-1.0);
      if value >= 0.0 && value.fract() == 0.0 {
        groups = groups.max(value as usize + 1);
      }
    }
  }
  if groups == 0 {
    r.fill(NumT::nan());
    return Ok(());
  }

  let mut aggregated = vec![NumT::nan(); groups * rows];
  aggregated
    .par_chunks_mut(rows)
    .enumerate()
    .for_each(|(group, out)| {
      for t in 0..rows {
        let mut sum = NumT::zero();
        let mut weight_sum = NumT::zero();
        let mut count = 0usize;
        let mut min_value = NumT::nan();
        let mut max_value = NumT::nan();
        for e in 0..entities {
          let cat = category[e];
          if !is_normal(&cat) {
            continue;
          }
          let value = cat.to_f64().unwrap_or(-1.0);
          if value < 0.0 || value.fract() != 0.0 || value as usize != group {
            continue;
          }
          let x = input[e * rows + t];
          if !is_normal(&x) {
            continue;
          }
          let w = if has_weight { weight[e * rows + t] } else { NumT::one() };
          if has_weight && !is_normal(&w) {
            continue;
          }
          sum = sum + x * w;
          weight_sum = weight_sum + w;
          if count == 0 || x < min_value {
            min_value = x;
          }
          if count == 0 || x > max_value {
            max_value = x;
          }
          count += 1;
        }
        if count == 0 {
          continue;
        }
        let n = NumT::from(count).unwrap();
        out[t] = match op {
          GROUP_MEAN => sum / n,
          GROUP_SUM => sum,
          GROUP_COUNT => n,
          GROUP_MIN => min_value,
          GROUP_MAX => max_value,
          GROUP_WEIGHTED_MEAN => {
            if weight_sum != NumT::zero() { sum / weight_sum } else { NumT::nan() }
          }
          _ => NumT::nan(),
        };
      }
    });

  for e in 0..entities {
    let cat = category[e];
    let group = if is_normal(&cat) {
      let value = cat.to_f64().unwrap_or(-1.0);
      if value >= 0.0 && value.fract() == 0.0 {
        Some(value as usize)
      } else {
        None
      }
    } else {
      None
    };
    for t in 0..rows {
      r[e * rows + t] = match group {
        Some(g) if g < groups => aggregated[g * rows + t],
        _ => NumT::nan(),
      };
    }
  }
  Ok(())
}
