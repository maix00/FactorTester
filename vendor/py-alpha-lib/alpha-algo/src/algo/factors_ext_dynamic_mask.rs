// Copyright 2026 MSD-RS Project LiJia
// SPDX-License-Identifier: BSD-2-Clause

use num_traits::Float;
use rayon::prelude::*;

use crate::algo::{is_normal, Context, Error};

/// Apply the pandas-compatible dynamic truncation mask to a rolling panel.
///
/// ``starts``/``ends`` are offsets evaluated at the window end row; masked
/// entries become NaN and the caller runs the normal rolling kernel afterwards.
pub fn ta_ft_dynamic_mask<NumT: Float + Send + Sync>(
  _ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  starts: &[NumT],
  ends: &[NumT],
  period: usize,
) -> Result<(), Error> {
  if input.len() != r.len() || starts.len() != input.len() || ends.len() != input.len() {
    return Err(Error::LengthMismatch(input.len(), r.len()));
  }
  if period == 0 {
    return Err(Error::InvalidParameter("period must be positive".to_string()));
  }
  let entities = _ctx.groups().max(1);
  if input.len() % entities != 0 {
    return Err(Error::LengthMismatch(input.len(), entities));
  }
  let rows = input.len() / entities;
  r.par_chunks_mut(rows).enumerate().for_each(|(entity, out)| {
    let base = entity * rows;
    for t in 0..rows {
      out[t] = input[base + t];
    }
    if rows < period {
      return;
    }
    for t in period - 1..rows {
      let window_start = t - period + 1;
      let start_value = starts[base + t];
      if is_normal(&start_value) {
        let start = start_value.to_f64().unwrap_or(0.0);
        let extent = if start > 0.0 { start.floor() as usize } else { 0 };
        let limit = (window_start + extent).min(rows);
        for row in window_start..limit {
          out[row] = NumT::nan();
        }
      }
      let end_value = ends[base + t];
      if is_normal(&end_value) {
        let end = end_value.to_f64().unwrap_or(period as f64 - 1.0);
        if end < period as f64 - 1.0 {
          let extent = if end > 0.0 { end.floor() as usize } else { 0 };
          let start = t.saturating_sub(extent);
          for row in start..=t {
            out[row] = NumT::nan();
          }
        }
      }
    }
  });
  Ok(())
}
