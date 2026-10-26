// Copyright 2026 MSD-RS Project LiJia
// SPDX-License-Identifier: BSD-2-Clause
//
// Session-spanning rolling windows.  A `250d` factor window contains every
// minute bar in the last 250 trading sessions, so its bar count changes at
// session boundaries.  This path keeps an O(1) running state and never scans
// the historical window per bar.

use std::collections::VecDeque;

use num_traits::Float;

use crate::algo::{Context, Error};

fn validate(
  values: &[f64],
  session_ids: &[u32],
  lookback_sessions: usize,
) -> Result<(), Error> {
  if values.len() != session_ids.len() {
    return Err(Error::LengthMismatch(values.len(), session_ids.len()));
  }
  if lookback_sessions == 0 {
    return Err(Error::InvalidParameter("lookback must be positive".to_string()));
  }
  if session_ids.windows(2).any(|pair| pair[0] > pair[1]) {
    return Err(Error::InvalidParameter("session ids must be non-decreasing".to_string()));
  }
  Ok(())
}

fn session_rolling<NumT, F>(
  _ctx: &Context,
  values: &[f64],
  session_ids: &[u32],
  lookback_sessions: usize,
  aggregate: F,
) -> Result<Vec<NumT>, Error>
where
  NumT: Float,
  F: Fn(f64, usize) -> NumT,
{
  validate(values, session_ids, lookback_sessions)?;
  let mut ring: VecDeque<(u32, f64)> = VecDeque::new();
  let mut finite_sum = 0.0f64;
  let mut finite_count = 0usize;
  let mut out = Vec::with_capacity(values.len());
  for (index, value) in values.iter().copied().enumerate() {
    let session = session_ids[index];
    let first_session = (session + 1).saturating_sub(lookback_sessions as u32);
    while ring.front().is_some_and(|(id, _)| *id < first_session) {
      if let Some((_, old)) = ring.pop_front() {
        if old.is_finite() {
          finite_sum -= old;
          finite_count -= 1;
        }
      }
    }
    ring.push_back((session, value));
    if value.is_finite() {
      finite_sum += value;
      finite_count += 1;
    }
    out.push(aggregate(finite_sum, finite_count));
  }
  Ok(out)
}

pub fn ta_session_rolling_sum<NumT: Float>(
  ctx: &Context,
  values: &[f64],
  session_ids: &[u32],
  lookback_sessions: usize,
) -> Result<Vec<NumT>, Error> {
  session_rolling(ctx, values, session_ids, lookback_sessions, |sum, count| {
    if count == 0 { NumT::nan() } else { NumT::from(sum).unwrap() }
  })
}

pub fn ta_session_rolling_mean<NumT: Float>(
  ctx: &Context,
  values: &[f64],
  session_ids: &[u32],
  lookback_sessions: usize,
) -> Result<Vec<NumT>, Error> {
  session_rolling(ctx, values, session_ids, lookback_sessions, |sum, count| {
    if count == 0 { NumT::nan() } else { NumT::from(sum / (count as f64)).unwrap() }
  })
}

#[cfg(test)]
mod tests {
  use super::*;

  #[test]
  fn session_window_expands_and_evicts() {
    let values = [1.0, 2.0, 3.0, 4.0, 5.0];
    let sessions = [0u32, 0, 1, 1, 1];
    let ctx = Context::default();
    let sum: Vec<f64> = ta_session_rolling_sum(&ctx, &values, &sessions, 2).unwrap();
    assert_eq!(sum, vec![1.0, 3.0, 6.0, 10.0, 15.0]);
    let mean: Vec<f64> = ta_session_rolling_mean(&ctx, &values, &sessions, 2).unwrap();
    assert_eq!(mean, vec![1.0, 1.5, 2.0, 2.5, 3.0]);
  }

  #[test]
  fn one_session_lookback_evicts_previous_session() {
    let values = [1.0, 2.0, 3.0, 4.0, 5.0];
    let sessions = [0u32, 0, 1, 1, 1];
    let ctx = Context::default();
    let sum: Vec<f64> = ta_session_rolling_sum(&ctx, &values, &sessions, 1).unwrap();
    assert_eq!(sum, vec![1.0, 3.0, 3.0, 7.0, 12.0]);
  }
}
