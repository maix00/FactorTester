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
#[derive(Clone, Copy, Debug)]
struct OstNode {
  key: f64,
  count: usize,
  size: usize,
  priority: u64,
  left: Option<usize>,
  right: Option<usize>,
}

#[derive(Default)]
struct OrderStatisticTree {
  nodes: Vec<OstNode>,
  root: Option<usize>,
}

impl OrderStatisticTree {
  fn size(node: Option<usize>, nodes: &[OstNode]) -> usize {
    node.map(|index| nodes[index].size).unwrap_or(0)
  }

  fn refresh(&mut self, node: usize) {
    let left = Self::size(self.nodes[node].left, &self.nodes);
    let right = Self::size(self.nodes[node].right, &self.nodes);
    self.nodes[node].size = left + self.nodes[node].count + right;
  }

  fn priority(key: f64) -> u64 {
    let mut bits = key.to_bits();
    bits ^= bits >> 33;
    bits = bits.wrapping_mul(0xff51afd7ed558ccd);
    bits ^= bits >> 33;
    bits = bits.wrapping_mul(0xc4ceb9fe1a85ec53);
    bits ^= bits >> 33;
    bits
  }

  fn rotate_right(&mut self, node: usize) -> usize {
    let left = self.nodes[node].left.unwrap();
    self.nodes[node].left = self.nodes[left].right;
    self.nodes[left].right = Some(node);
    self.refresh(node);
    self.refresh(left);
    left
  }

  fn rotate_left(&mut self, node: usize) -> usize {
    let right = self.nodes[node].right.unwrap();
    self.nodes[node].right = self.nodes[right].left;
    self.nodes[right].left = Some(node);
    self.refresh(node);
    self.refresh(right);
    right
  }

  fn insert_at(&mut self, node: Option<usize>, key: f64, priority: u64) -> usize {
    let Some(index) = node else {
      let index = self.nodes.len();
      self.nodes.push(OstNode { key, count: 1, size: 1, priority, left: None, right: None });
      return index;
    };
    if key == self.nodes[index].key {
      self.nodes[index].count += 1;
      self.refresh(index);
      return index;
    }
    if key < self.nodes[index].key {
      let child = self.insert_at(self.nodes[index].left, key, priority);
      self.nodes[index].left = Some(child);
      self.refresh(index);
      if self.nodes[child].priority > self.nodes[index].priority {
        return self.rotate_right(index);
      }
    } else {
      let child = self.insert_at(self.nodes[index].right, key, priority);
      self.nodes[index].right = Some(child);
      self.refresh(index);
      if self.nodes[child].priority > self.nodes[index].priority {
        return self.rotate_left(index);
      }
    }
    index
  }

  fn merge(&mut self, left: Option<usize>, right: Option<usize>) -> Option<usize> {
    match (left, right) {
      (None, node) | (node, None) => node,
      (Some(l), Some(r)) => {
        if self.nodes[l].priority > self.nodes[r].priority {
          let new_right = self.merge(self.nodes[l].right, Some(r));
          self.nodes[l].right = new_right;
          self.refresh(l);
          Some(l)
        } else {
          let new_left = self.merge(Some(l), self.nodes[r].left);
          self.nodes[r].left = new_left;
          self.refresh(r);
          Some(r)
        }
      }
    }
  }

  fn remove_at(&mut self, node: Option<usize>, key: f64) -> Option<usize> {
    let index = node?;
    if key == self.nodes[index].key {
      if self.nodes[index].count > 1 {
        self.nodes[index].count -= 1;
        self.refresh(index);
        return Some(index);
      }
      return self.merge(self.nodes[index].left, self.nodes[index].right);
    }
    if key < self.nodes[index].key {
      self.nodes[index].left = self.remove_at(self.nodes[index].left, key);
    } else {
      self.nodes[index].right = self.remove_at(self.nodes[index].right, key);
    }
    self.refresh(index);
    Some(index)
  }

  fn insert(&mut self, key: f64) {
    let priority = Self::priority(key);
    self.root = Some(self.insert_at(self.root, key, priority));
  }

  fn remove(&mut self, key: f64) {
    self.root = self.remove_at(self.root, key);
  }

  fn rank_le(&self, key: f64) -> usize {
    let mut node = self.root;
    let mut total = 0;
    while let Some(index) = node {
      if key < self.nodes[index].key {
        node = self.nodes[index].left;
      } else {
        total += Self::size(self.nodes[index].left, &self.nodes) + self.nodes[index].count;
        node = self.nodes[index].right;
      }
    }
    total
  }

  fn kth(&self, mut k: usize) -> Option<f64> {
    let mut node = self.root;
    while let Some(index) = node {
      let left = Self::size(self.nodes[index].left, &self.nodes);
      if k < left {
        node = self.nodes[index].left;
      } else if k < left + self.nodes[index].count {
        return Some(self.nodes[index].key);
      } else {
        k -= left + self.nodes[index].count;
        node = self.nodes[index].right;
      }
    }
    None
  }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum SessionOp {
  Sum,
  Mean,
  Var,
  Std,
  Min,
  Max,
  Skew,
  Argmin,
  Argmax,
  Quantile(f64),
  Rank,
}

pub struct SessionWindowState {
  lookback_sessions: u32,
  op: SessionOp,
  ring: VecDeque<(u32, f64, u64)>,
  finite_sum: f64,
  finite_sumsq: f64,
  finite_sum3: f64,
  finite_count: usize,
  next_index: u64,
  min_deque: VecDeque<(u64, f64)>,
  max_deque: VecDeque<(u64, f64)>,
  order_stat: Option<OrderStatisticTree>,
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
      finite_sum3: 0.0,
      finite_count: 0,
      next_index: 0,
      min_deque: VecDeque::new(),
      max_deque: VecDeque::new(),
      order_stat: if matches!(op, SessionOp::Quantile(_) | SessionOp::Rank) {
        Some(OrderStatisticTree::default())
      } else {
        None
      },
    })
  }

  fn remove_oldest(&mut self) {
    let Some((_session, old, index)) = self.ring.pop_front() else { return };
    if old.is_finite() {
      self.finite_sum -= old;
      self.finite_sumsq -= old * old;
      self.finite_sum3 -= old * old * old;
      self.finite_count -= 1;
      if let Some(tree) = self.order_stat.as_mut() { tree.remove(old); }
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
      self.finite_sum3 += value * value * value;
      self.finite_count += 1;
      if let Some(tree) = self.order_stat.as_mut() { tree.insert(value); }
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
      SessionOp::Argmin | SessionOp::Argmax => {
        let deque = if self.op == SessionOp::Argmax { &self.max_deque } else { &self.min_deque };
        let Some((index, _)) = deque.front() else { return f64::NAN };
        let current = self.next_index.saturating_sub(1);
        if count <= 1 { 0.0 } else { (current - *index) as f64 / (count - 1) as f64 }
      }
      SessionOp::Rank => {
        let Some(tree) = self.order_stat.as_ref() else { return f64::NAN };
        if !value.is_finite() { f64::NAN } else {
          tree.rank_le(value) as f64 / count as f64
        }
      }
      SessionOp::Quantile(q) => {
        let Some(tree) = self.order_stat.as_ref() else { return f64::NAN };
        let position = q.clamp(0.0, 1.0) * (count - 1) as f64;
        let lower = position.floor() as usize;
        let upper = position.ceil() as usize;
        let (Some(low), Some(high)) = (tree.kth(lower), tree.kth(upper)) else {
          return f64::NAN;
        };
        low + (high - low) * (position - lower as f64)
      }
      SessionOp::Skew => {
        if count < 3 {
          f64::NAN
        } else {
          let n = count as f64;
          let mean = self.finite_sum / n;
          let m2 = (self.finite_sumsq - self.finite_sum * self.finite_sum / n).max(0.0);
          let m3 = self.finite_sum3 - 3.0 * mean * self.finite_sumsq
            + 2.0 * n * mean * mean * mean;
          if m2 <= 0.0 {
            f64::NAN
          } else {
            let population = (m3 / n) / (m2 / n).powf(1.5);
            population * (n * (n - 1.0)).sqrt() / (n - 2.0)
          }
        }
      }
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

pub fn ta_session_rolling_argmin<NumT: Float>(
  values: &[f64], session_ids: &[u32], lookback_sessions: usize,
) -> Result<Vec<NumT>, Error> {
  session_rolling_state(values, session_ids, lookback_sessions, SessionOp::Argmin)
}

pub fn ta_session_rolling_argmax<NumT: Float>(
  values: &[f64], session_ids: &[u32], lookback_sessions: usize,
) -> Result<Vec<NumT>, Error> {
  session_rolling_state(values, session_ids, lookback_sessions, SessionOp::Argmax)
}

pub fn ta_session_rolling_skew<NumT: Float>(
  values: &[f64], session_ids: &[u32], lookback_sessions: usize,
) -> Result<Vec<NumT>, Error> {
  session_rolling_state(values, session_ids, lookback_sessions, SessionOp::Skew)
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

struct Fenwick {
  tree: Vec<usize>,
  size: usize,
}

impl Fenwick {
  fn new(size: usize) -> Self { Self { tree: vec![0; size + 1], size } }
  fn add(&mut self, index: usize, delta: isize) {
    let mut i = index + 1;
    while i <= self.size {
      self.tree[i] = (self.tree[i] as isize + delta).max(0) as usize;
      i += i & i.wrapping_neg();
    }
  }
  fn prefix(&self, index: usize) -> usize {
    let mut i = index + 1;
    let mut total = 0;
    while i > 0 { total += self.tree[i]; i -= i & i.wrapping_neg(); }
    total
  }
  fn kth(&self, mut k: usize) -> usize {
    let mut index = 0usize;
    let mut bit = self.size.next_power_of_two();
    while bit > 0 {
      let next = index + bit;
      if next <= self.size && self.tree[next] < k {
        index = next;
        k -= self.tree[next];
      }
      bit >>= 1;
    }
    index
  }
}

fn session_quantile_like(
  values: &[f64], session_ids: &[u32], lookback_sessions: usize,
  quantile: Option<f64>, rank: bool,
) -> Result<Vec<f64>, Error> {
  validate(values, session_ids, lookback_sessions)?;
  let mut coordinates: Vec<f64> = values.iter().copied().filter(|v| v.is_finite()).collect();
  coordinates.sort_by(|a, b| a.partial_cmp(b).unwrap());
  coordinates.dedup();
  if coordinates.is_empty() { return Ok(vec![f64::NAN; values.len()]); }
  let lookup = |value: f64| -> usize {
    coordinates.partition_point(|candidate| *candidate < value)
  };
  let mut fenwick = Fenwick::new(coordinates.len());
  let mut ring: VecDeque<(u32, f64)> = VecDeque::new();
  let mut out = Vec::with_capacity(values.len());
  for (index, value) in values.iter().copied().enumerate() {
    let session = session_ids[index];
    let first_session = (session + 1).saturating_sub(lookback_sessions as u32);
    while ring.front().is_some_and(|(id, _)| *id < first_session) {
      if let Some((_, old)) = ring.pop_front() {
        if old.is_finite() { fenwick.add(lookup(old), -1); }
      }
    }
    ring.push_back((session, value));
    if value.is_finite() { fenwick.add(lookup(value), 1); }
    let total = fenwick.prefix(coordinates.len() - 1);
    if total == 0 {
      out.push(f64::NAN);
    } else if rank {
      if !value.is_finite() {
        out.push(f64::NAN);
      } else {
        let below = fenwick.prefix(lookup(value));
        out.push(below as f64 / total as f64);
      }
    } else {
      let q = quantile.unwrap_or(0.5).clamp(0.0, 1.0);
      let position = q * (total - 1) as f64;
      let lower = position.floor() as usize;
      let upper = position.ceil() as usize;
      let lower_v = coordinates[fenwick.kth(lower + 1)];
      let upper_v = coordinates[fenwick.kth(upper + 1)];
      out.push(lower_v + (upper_v - lower_v) * (position - lower as f64));
    }
  }
  Ok(out)
}

pub fn ta_session_rolling_quantile(
  values: &[f64], session_ids: &[u32], lookback_sessions: usize, quantile: f64,
) -> Result<Vec<f64>, Error> {
  session_quantile_like(values, session_ids, lookback_sessions, Some(quantile), false)
}

pub fn ta_session_rolling_rank(
  values: &[f64], session_ids: &[u32], lookback_sessions: usize,
) -> Result<Vec<f64>, Error> {
  session_quantile_like(values, session_ids, lookback_sessions, None, true)
}

/// Time-boundary rolling state for sub-day windows that may cross sessions.
/// A bar belongs to the window when its timestamp is within `duration_ns` of
/// the current bar, regardless of session breaks.
pub struct TimeWindowState {
  duration_ns: i64,
  ring: VecDeque<(i64, f64)>,
  sum: f64,
  count: usize,
  mean: bool,
}

impl TimeWindowState {
  pub fn new(duration_ns: i64, mean: bool) -> Result<Self, Error> {
    if duration_ns <= 0 {
      return Err(Error::InvalidParameter("duration must be positive".to_string()));
    }
    Ok(Self { duration_ns, ring: VecDeque::new(), sum: 0.0, count: 0, mean })
  }

  pub fn update(&mut self, timestamp_ns: i64, value: f64) -> f64 {
    if let Some((last, _)) = self.ring.back() {
      if timestamp_ns < *last { return f64::NAN; }
    }
    while self.ring.front().is_some_and(|(ts, _)| timestamp_ns - *ts > self.duration_ns) {
      if let Some((_, old)) = self.ring.pop_front() {
        if old.is_finite() { self.sum -= old; self.count -= 1; }
      }
    }
    self.ring.push_back((timestamp_ns, value));
    if value.is_finite() { self.sum += value; self.count += 1; }
    if self.count == 0 { f64::NAN }
    else if self.mean { self.sum / self.count as f64 }
    else { self.sum }
  }
}

fn time_rolling(
  timestamps: &[i64], values: &[f64], duration_ns: i64, mean: bool,
) -> Result<Vec<f64>, Error> {
  if timestamps.len() != values.len() {
    return Err(Error::LengthMismatch(timestamps.len(), values.len()));
  }
  let mut state = TimeWindowState::new(duration_ns, mean)?;
  Ok(timestamps.iter().copied().zip(values.iter().copied())
    .map(|(ts, value)| state.update(ts, value)).collect())
}

pub fn ta_time_rolling_sum(timestamps: &[i64], values: &[f64], duration_ns: i64) -> Result<Vec<f64>, Error> {
  time_rolling(timestamps, values, duration_ns, false)
}

pub fn ta_time_rolling_mean(timestamps: &[i64], values: &[f64], duration_ns: i64) -> Result<Vec<f64>, Error> {
  time_rolling(timestamps, values, duration_ns, true)
}

fn session_rolling_pair(
  x: &[f64], y: &[f64], session_ids: &[u32], lookback_sessions: usize,
  correlation: bool,
) -> Result<Vec<f64>, Error> {
  if x.len() != y.len() {
    return Err(Error::LengthMismatch(x.len(), y.len()));
  }
  validate(x, session_ids, lookback_sessions)?;
  let mut ring: VecDeque<(u32, f64, f64)> = VecDeque::new();
  let (mut sx, mut sy, mut sxx, mut syy, mut sxy, mut count) =
    (0.0, 0.0, 0.0, 0.0, 0.0, 0usize);
  let mut out = Vec::with_capacity(x.len());
  for index in 0..x.len() {
    let session = session_ids[index];
    let first_session = (session + 1).saturating_sub(lookback_sessions as u32);
    while ring.front().is_some_and(|(id, _, _)| *id < first_session) {
      if let Some((_, ox, oy)) = ring.pop_front() {
        if ox.is_finite() && oy.is_finite() {
          sx -= ox; sy -= oy; sxx -= ox * ox; syy -= oy * oy; sxy -= ox * oy;
          count -= 1;
        }
      }
    }
    let (vx, vy) = (x[index], y[index]);
    ring.push_back((session, vx, vy));
    if vx.is_finite() && vy.is_finite() {
      sx += vx; sy += vy; sxx += vx * vx; syy += vy * vy; sxy += vx * vy;
      count += 1;
    }
    if count < 2 {
      out.push(f64::NAN);
      continue;
    }
    let n = count as f64;
    let cov = (sxy - sx * sy / n) / (n - 1.0);
    if !correlation {
      out.push(cov);
    } else {
      let vx = (sxx - sx * sx / n).max(0.0);
      let vy = (syy - sy * sy / n).max(0.0);
      let denom = (vx * vy).sqrt();
      out.push(if denom > 0.0 { (sxy - sx * sy / n) / denom } else { f64::NAN });
    }
  }
  Ok(out)
}

pub fn ta_session_rolling_cov(
  x: &[f64], y: &[f64], session_ids: &[u32], lookback_sessions: usize,
) -> Result<Vec<f64>, Error> {
  session_rolling_pair(x, y, session_ids, lookback_sessions, false)
}

pub fn ta_session_rolling_corr(
  x: &[f64], y: &[f64], session_ids: &[u32], lookback_sessions: usize,
) -> Result<Vec<f64>, Error> {
  session_rolling_pair(x, y, session_ids, lookback_sessions, true)
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
  fn arg_extrema_report_window_offset() {
    let mut state = SessionWindowState::new_op(1, SessionOp::Argmax).unwrap();
    state.update(0, 1.0);
    state.update(0, 3.0);
    let value = state.update(0, 2.0);
    assert!((value - 0.5).abs() < 1e-12);
  }

  #[test]
  fn time_window_spans_session_break_by_timestamp() {
    let timestamps = [0i64, 1_000, 10_000, 11_000];
    let values = [1.0, 2.0, 3.0, 4.0];
    let sum = ta_time_rolling_sum(&timestamps, &values, 2_000).unwrap();
    assert_eq!(sum, vec![1.0, 3.0, 3.0, 7.0]);
  }

  #[test]
  fn streaming_quantile_rank_use_session_window() {
    let mut median = SessionWindowState::new_op(1, SessionOp::Quantile(0.5)).unwrap();
    median.update(0, 1.0);
    median.update(0, 2.0);
    assert_eq!(median.update(0, 3.0), 2.0);
    let mut rank = SessionWindowState::new_op(1, SessionOp::Rank).unwrap();
    rank.update(0, 1.0);
    rank.update(0, 2.0);
    assert!((rank.update(0, 3.0) - 1.0).abs() < 1e-12);
    assert_eq!(rank.update(1, 5.0), 1.0);
  }

  #[test]
  fn session_quantile_and_rank_use_only_window() {
    let values = [1.0, 2.0, 3.0, 4.0, 5.0];
    let sessions = [0u32, 0, 1, 1, 1];
    let q = ta_session_rolling_quantile(&values, &sessions, 1, 0.5).unwrap();

    assert!((q[1] - 1.5).abs() < 1e-12);
    assert!((q[2] - 3.0).abs() < 1e-12);
    let r = ta_session_rolling_rank(&values, &sessions, 1).unwrap();

    assert!((r[1] - 1.0).abs() < 1e-12);
  }

  #[test]
  fn streaming_skew_is_available() {
    let mut state = SessionWindowState::new_op(1, SessionOp::Skew).unwrap();
    for value in [1.0, 2.0, 3.0, 4.0] {
      let result = state.update(0, value);
      if value >= 3.0 {
        assert!(result.is_finite());
      }
    }
  }

  #[test]
  fn pair_cov_and_corr_respect_sessions() {
    let x = [1.0, 2.0, 3.0, 4.0];
    let y = [2.0, 4.0, 6.0, 8.0];
    let sessions = [0u32, 0, 1, 1];
    let corr = ta_session_rolling_corr(&x, &y, &sessions, 1).unwrap();
    assert!((corr[1] - 1.0).abs() < 1e-12);
    assert!((corr[3] - 1.0).abs() < 1e-12);
    let cov = ta_session_rolling_cov(&x, &y, &sessions, 1).unwrap();
    assert!((cov[1] - 1.0).abs() < 1e-12);
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
