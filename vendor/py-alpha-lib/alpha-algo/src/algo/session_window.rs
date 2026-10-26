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


/// Mutable run-scoped state for one session-spanning rolling operator.
///
/// The caller advances one bar at a time.  Eviction follows the session
/// ordinal, so the logical window can grow/shrink at session boundaries while
/// each update remains amortized O(1).
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SessionOp {
  Sum,
  Mean,
  Var,
  Std,
  Min,
  Max,
}

pub struct SessionWindowState {
  lookback_sessions: u32,
  op: SessionOp,
  ring: VecDeque<(u32, f64, u64)>,
  finite_sum: f64,
  finite_sumsq: f64,
  finite_count: usize,
  next_index: u64,
  min_deque: VecDeque<(u64, f64)>,
  max_deque: VecDeque<(u64, f64)>,
}

impl SessionWindowState {
  pub fn new(lookback_sessions: usize, mean: bool) -> Result<Self, Error> {
    Self::new_op(lookback_sessions, if mean { SessionOp::Mean } else { SessionOp::Sum })
  }

  pub fn new_op(lookback_sessions: usize, op: SessionOp) -> Result<Self, Error> {
    if lookback_sessions == 0 {
      return Err(Error::InvalidParameter("lookback must be positive".to_string()));
    }
    Ok(Self {
      lookback_sessions: lookback_sessions as u32,
      op,
      ring: VecDeque::new(),
      finite_sum: 0.0,
      finite_sumsq: 0.0,
      finite_count: 0,
      next_index: 0,
      min_deque: VecDeque::new(),
      max_deque: VecDeque::new(),
    })
  }

  fn remove_oldest(&mut self) {
    let Some((_session, old, index)) = self.ring.pop_front() else { return };
    if old.is_finite() {
      self.finite_sum -= old;
      self.finite_sumsq -= old * old;
      self.finite_count -= 1;
    }
    while self.min_deque.front().is_some_and(|(i, _)| *i <= index) {
      self.min_deque.pop_front();
    }
    while self.max_deque.front().is_some_and(|(i, _)| *i <= index) {
      self.max_deque.pop_front();
    }
  }

  pub fn update(&mut self, session_id: u32, value: f64) -> f64 {
    if let Some((last, _, _)) = self.ring.back() {
      if session_id < *last {
        return f64::NAN;
      }
    }
    let first_session = (session_id + 1).saturating_sub(self.lookback_sessions);
    while self.ring.front().is_some_and(|(id, _, _)| *id < first_session) {
      self.remove_oldest();
    }
    let index = self.next_index;
    self.next_index += 1;
    self.ring.push_back((session_id, value, index));
    if value.is_finite() {
      self.finite_sum += value;
      self.finite_sumsq += value * value;
      self.finite_count += 1;
      while self.min_deque.back().is_some_and(|(_, v)| *v >= value) {
        self.min_deque.pop_back();
      }
      self.min_deque.push_back((index, value));
      while self.max_deque.back().is_some_and(|(_, v)| *v <= value) {
        self.max_deque.pop_back();
      }
      self.max_deque.push_back((index, value));
    }
    let count = self.finite_count;
    if count == 0 {
      return f64::NAN;
    }
    match self.op {
      SessionOp::Sum => self.finite_sum,
      SessionOp::Mean => self.finite_sum / count as f64,
      SessionOp::Var | SessionOp::Std => {
        if count < 2 {
          f64::NAN
        } else {
          let variance = ((self.finite_sumsq - self.finite_sum * self.finite_sum / count as f64)
            / (count - 1) as f64)
            .max(0.0);
          if self.op == SessionOp::Var { variance } else { variance.sqrt() }
        }
      }
      SessionOp::Min => self.min_deque.front().map(|(_, v)| *v).unwrap_or(f64::NAN),
      SessionOp::Max => self.max_deque.front().map(|(_, v)| *v).unwrap_or(f64::NAN),
    }
  }
}

fn session_rolling_state<NumT: Float>(
  values: &[f64],
  session_ids: &[u32],
  lookback_sessions: usize,
  op: SessionOp,
) -> Result<Vec<NumT>, Error> {
  validate(values, session_ids, lookback_sessions)?;
  let mut state = SessionWindowState::new_op(lookback_sessions, op)?;
  let mut out = Vec::with_capacity(values.len());
  for (value, session) in values.iter().zip(session_ids.iter()) {
    out.push(NumT::from(state.update(*session, *value)).unwrap());
  }
  Ok(out)
}

pub fn ta_session_rolling_var<NumT: Float>(
  values: &[f64], session_ids: &[u32], lookback_sessions: usize,
) -> Result<Vec<NumT>, Error> {
  session_rolling_state(values, session_ids, lookback_sessions, SessionOp::Var)
}

pub fn ta_session_rolling_std<NumT: Float>(
  values: &[f64], session_ids: &[u32], lookback_sessions: usize,
) -> Result<Vec<NumT>, Error> {
  session_rolling_state(values, session_ids, lookback_sessions, SessionOp::Std)
}

pub fn ta_session_rolling_min<NumT: Float>(
  values: &[f64], session_ids: &[u32], lookback_sessions: usize,
) -> Result<Vec<NumT>, Error> {
  session_rolling_state(values, session_ids, lookback_sessions, SessionOp::Min)
}

pub fn ta_session_rolling_max<NumT: Float>(
  values: &[f64], session_ids: &[u32], lookback_sessions: usize,
) -> Result<Vec<NumT>, Error> {
  session_rolling_state(values, session_ids, lookback_sessions, SessionOp::Max)
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
  fn streaming_state_matches_batch_semantics() {
    let mut state = SessionWindowState::new(1, false).unwrap();
    assert_eq!(state.update(0, 1.0), 1.0);
    assert_eq!(state.update(0, 2.0), 3.0);
    assert_eq!(state.update(1, 3.0), 3.0);
    assert_eq!(state.update(1, 4.0), 7.0);
    assert_eq!(state.update(1, 5.0), 12.0);
  }

  #[test]
  fn streaming_state_supports_var_std_min_max() {
    let mut var = SessionWindowState::new_op(1, SessionOp::Var).unwrap();
    var.update(0, 1.0);
    var.update(0, 2.0);
    let value = var.update(0, 4.0);
    assert!((value - 7.0 / 3.0).abs() < 1e-12);
    let mut std = SessionWindowState::new_op(1, SessionOp::Std).unwrap();
    std.update(0, 1.0);
    std.update(0, 2.0);
    std.update(0, 4.0);
    let value = std.update(0, 4.0);
    assert!(value.is_finite());
    let mut min = SessionWindowState::new_op(1, SessionOp::Min).unwrap();
    min.update(0, 5.0);
    min.update(0, 2.0);
    assert_eq!(min.update(1, 7.0), 7.0);
    let mut max = SessionWindowState::new_op(1, SessionOp::Max).unwrap();
    max.update(0, 5.0);
    max.update(0, 2.0);
    assert_eq!(max.update(1, 7.0), 7.0);
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
