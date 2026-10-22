// Copyright 2026 MSD-RS Project LiJia
// SPDX-License-Identifier: BSD-2-Clause

use num_traits::Float;
use rayon::prelude::*;

use crate::algo::{is_normal, Context, Error};

/// Dynamic truncated rolling arg-extreme.
///
/// ``starts``/``ends`` are per-window offsets evaluated at the window end row
/// (NaN means no truncation on that side). Output keeps the input shape;
/// warmup ``period - 1`` rows stay NaN. Ties choose the most recent bar and an
/// empty range returns 0, matching the pandas reference.
pub fn ta_ft_dynamic_arg<NumT: Float + Send + Sync>(
  _ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  starts: &[NumT],
  ends: &[NumT],
  period: usize,
  flags: usize,
) -> Result<(), Error> {
  let normalize = flags & 1 != 0;
  let is_max = flags & 2 != 0;
  if input.len() != r.len() || starts.len() != input.len() || ends.len() != input.len() {
    return Err(Error::LengthMismatch(input.len(), r.len()));
  }
  if period == 0 {
    return Err(Error::InvalidParameter("period must be positive".to_string()));
  }
  // Binding flattens (entities, rows); entity count comes from the context.
  let entities = _ctx.groups().max(1);
  if input.len() % entities != 0 {
    return Err(Error::LengthMismatch(input.len(), entities));
  }
  let rows = input.len() / entities;
  r.par_chunks_mut(rows).enumerate().for_each(|(entity, out)| {
    for value in out.iter_mut() {
      *value = NumT::nan();
    }
    if rows < period {
      return;
    }
    for t in period - 1..rows {
      let base = entity * rows;
      let index = t - period + 1;
      let raw_start = starts[base + t];
      let raw_end = ends[base + t];
      let start_value = if is_normal(&raw_start) { raw_start.to_f64().unwrap_or(0.0) } else { 0.0 };
      let end_value = if is_normal(&raw_end) {
        raw_end.to_f64().unwrap_or(period as f64 - 1.0)
      } else {
        period as f64 - 1.0
      };
      let start_i = start_value.floor() as i64;
      let end_i = end_value.floor() as i64;
      if start_i > period as i64 - 1 || end_i < 0 {
        out[t] = NumT::zero();
        continue;
      }
      let start = start_i.max(0) as usize;
      let end = end_i.min(period as i64 - 1) as usize;
      if end < start {
        out[t] = NumT::zero();
        continue;
      }
      let mut best_pos: Option<usize> = None;
      let mut best_value = NumT::nan();
      for offset in start..=end {
        let candidate = input[base + index + offset];
        if !is_normal(&candidate) {
          continue;
        }
        let better = match best_pos {
          None => true,
          Some(_) => {
            if is_max {
              candidate >= best_value
            } else {
              candidate <= best_value
            }
          }
        };
        if better {
          best_pos = Some(offset);
          best_value = candidate;
        }
      }
      out[t] = match best_pos {
        None => NumT::zero(),
        Some(position) => {
          if normalize {
            NumT::from(position).unwrap() / NumT::from(period - 1).unwrap()
          } else {
            NumT::from(position).unwrap()
          }
        }
      };
    }
  });
  Ok(())
}
