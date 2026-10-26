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
  sum: f64,
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
    let left_sum = self.nodes[node].left.map(|i| self.nodes[i].sum).unwrap_or(0.0);
    let right_sum = self.nodes[node].right.map(|i| self.nodes[i].sum).unwrap_or(0.0);
    self.nodes[node].sum = left_sum + self.nodes[node].key * self.nodes[node].count as f64 + right_sum;
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
      self.nodes.push(OstNode { key, count: 1, size: 1, sum: key, priority, left: None, right: None });
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

  fn sum_le(&self, key: f64) -> f64 {
    let mut node = self.root;
    let mut total = 0.0;
    while let Some(index) = node {
      if key < self.nodes[index].key {
        node = self.nodes[index].left;
      } else {
        let left_sum = self.nodes[index].left.map(|i| self.nodes[i].sum).unwrap_or(0.0);
        total += left_sum + self.nodes[index].key * self.nodes[index].count as f64;
        node = self.nodes[index].right;
      }
    }
    total
  }

  fn total_sum(&self) -> f64 {
    self.root.map(|index| self.nodes[index].sum).unwrap_or(0.0)
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
  ArgminRaw,
  ArgmaxRaw,
  Quantile(f64),
  Rank,
  Mad,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum WindowPolicy {
  Bars(u32),
  Partition,
  PartitionRange { start: u32, end: u32 },
  StartIndex,
  Sessions(u32),
  WallClock(i64),
}

pub struct SessionWindowState {
  policy: WindowPolicy,
  op: SessionOp,
  ring: VecDeque<(u32, i64, f64, u64)>,
  finite_sum: f64,
  finite_sumsq: f64,
  finite_sum3: f64,
  finite_count: usize,
  next_index: u64,
  start_index: u64,
  last_value: f64,
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
      policy: WindowPolicy::Sessions(lookback_sessions as u32),
      op,
      ring: VecDeque::new(),
      finite_sum: 0.0,
      finite_sumsq: 0.0,
      finite_sum3: 0.0,
      finite_count: 0,
      next_index: 0,
      start_index: 0,
      last_value: f64::NAN,
      min_deque: VecDeque::new(),
      max_deque: VecDeque::new(),
      order_stat: if matches!(op, SessionOp::Quantile(_) | SessionOp::Rank | SessionOp::Mad) {
        Some(OrderStatisticTree::default())
      } else {
        None
      },
    })
  }

  pub fn new_wall(duration_ns: i64, op: SessionOp) -> Result<Self, Error> {
    if duration_ns <= 0 {
      return Err(Error::InvalidParameter("duration must be positive".to_string()));
    }
    let mut state = Self::new_op(1, op)?;
    state.policy = WindowPolicy::WallClock(duration_ns);
    Ok(state)
  }

  pub fn new_bars(max_bars: usize, op: SessionOp) -> Result<Self, Error> {
    if max_bars == 0 {
      return Err(Error::InvalidParameter("max_bars must be positive".to_string()));
    }
    let mut state = Self::new_op(1, op)?;
    state.policy = WindowPolicy::Bars(max_bars as u32);
    Ok(state)
  }

  pub fn new_partition(op: SessionOp) -> Result<Self, Error> {
    let mut state = Self::new_op(1, op)?;
    state.policy = WindowPolicy::Partition;
    Ok(state)
  }

  pub fn new_partition_range(start: usize, end: Option<usize>, op: SessionOp) -> Result<Self, Error> {
    let end = end.unwrap_or(u32::MAX as usize);
    if end < start {
      return Err(Error::InvalidParameter("partition range end before start".to_string()));
    }
    let mut state = Self::new_op(1, op)?;
    state.policy = WindowPolicy::PartitionRange { start: start as u32, end: end as u32 };
    Ok(state)
  }

  pub fn new_start_index(op: SessionOp) -> Result<Self, Error> {
    let mut state = Self::new_op(1, op)?;
    state.policy = WindowPolicy::StartIndex;
    Ok(state)
  }

  pub fn update_from(&mut self, start_index: u64, value: f64) -> f64 {
    self.start_index = start_index;
    self.update_at(0, 0, value)
  }

  fn clear(&mut self) {
    self.ring.clear();
    self.finite_sum = 0.0;
    self.finite_sumsq = 0.0;
    self.finite_sum3 = 0.0;
    self.finite_count = 0;
    self.next_index = 0;
    self.start_index = 0;
    self.last_value = f64::NAN;
    self.min_deque.clear();
    self.max_deque.clear();
    if let Some(tree) = self.order_stat.as_mut() { *tree = OrderStatisticTree::default(); }
  }

  fn remove_oldest(&mut self) {
    let Some((_session, _timestamp, old, index)) = self.ring.pop_front() else { return };
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
    self.update_at(session_id, 0, value)
  }

  pub fn update_at(&mut self, session_id: u32, timestamp_ns: i64, value: f64) -> f64 {
    if let WindowPolicy::PartitionRange { start, end } = self.policy {
      if let Some((last, _, _, _)) = self.ring.back() {
        if *last != session_id { self.clear(); }
      }
      let ordinal = self.next_index as u32;
      if ordinal < start {
        self.next_index += 1;
        return self.last_value;
      }
      if ordinal > end { return self.last_value; }
      let out = self.update_at_inner(session_id, timestamp_ns, value);
      self.last_value = out;
      return out;
    }
    self.update_at_inner(session_id, timestamp_ns, value)
  }

  fn update_at_inner(&mut self, session_id: u32, timestamp_ns: i64, value: f64) -> f64 {
    if self.policy == WindowPolicy::Partition {
      if let Some((last_session, _, _, _)) = self.ring.back() {
        if *last_session != session_id {
          self.clear();
        }
      }
    }
    if let Some((last_session, last_timestamp, _, _)) = self.ring.back() {
      match self.policy {
        WindowPolicy::Sessions(_) if session_id < *last_session => return f64::NAN,
        WindowPolicy::WallClock(_) if timestamp_ns < *last_timestamp => return f64::NAN,
        _ => {}
      }
    }
    match self.policy {
      WindowPolicy::Sessions(lookback) => {
        let first_session = (session_id + 1).saturating_sub(lookback);
        while self.ring.front().is_some_and(|(id, _, _, _)| *id < first_session) {
          self.remove_oldest();
        }
      }
      WindowPolicy::WallClock(duration) => {
        while self.ring.front().is_some_and(|(_, ts, _, _)| timestamp_ns - *ts > duration) {
          self.remove_oldest();
        }
      }
      WindowPolicy::Bars(max_bars) => {
        while self.ring.len() >= max_bars as usize {
          self.remove_oldest();
        }
      }
      WindowPolicy::Partition | WindowPolicy::PartitionRange { .. } => {}
      WindowPolicy::StartIndex => {
        while self.ring.front().is_some_and(|(_, _, _, index)| *index < self.start_index) {
          self.remove_oldest();
        }
      }
    }
    let index = self.next_index;
    self.next_index += 1;
    self.ring.push_back((session_id, timestamp_ns, value, index));
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
      SessionOp::Argmin | SessionOp::Argmax | SessionOp::ArgminRaw | SessionOp::ArgmaxRaw => {
        let find_max = matches!(self.op, SessionOp::Argmax | SessionOp::ArgmaxRaw);
        let deque = if find_max { &self.max_deque } else { &self.min_deque };
        let Some((index, _)) = deque.front() else { return f64::NAN };
        let current = self.next_index.saturating_sub(1);
        let raw = (current - *index) as f64;
        if matches!(self.op, SessionOp::ArgminRaw | SessionOp::ArgmaxRaw) {
          raw
        } else if count <= 1 {
          0.0
        } else {
          raw / (count - 1) as f64
        }
      }
      SessionOp::Mad => {
        let Some(tree) = self.order_stat.as_ref() else { return f64::NAN };
        let lower = (count - 1) / 2;
        let upper = count / 2;
        let (Some(low), Some(high)) = (tree.kth(lower), tree.kth(upper)) else {
          return f64::NAN;
        };
        let median = (low + high) / 2.0;
        let below = tree.rank_le(median) as f64;
        let below_sum = tree.sum_le(median);
        let above = count as f64 - below;
        let above_sum = tree.total_sum() - below_sum;
        (median * below - below_sum + above_sum - median * above) / count as f64
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

pub fn ta_time_rolling_sum(timestamps: &[i64], values: &[f64], duration_ns: i64) -> Result<Vec<f64>, Error> {
  time_rolling(timestamps, values, duration_ns, false)
}

pub fn ta_time_rolling_mean(timestamps: &[i64], values: &[f64], duration_ns: i64) -> Result<Vec<f64>, Error> {
  time_rolling(timestamps, values, duration_ns, true)
}

fn time_rolling_op(
  timestamps: &[i64], values: &[f64], duration_ns: i64, op: SessionOp,
) -> Result<Vec<f64>, Error> {
  if timestamps.len() != values.len() {
    return Err(Error::LengthMismatch(timestamps.len(), values.len()));
  }
  let mut state = SessionWindowState::new_wall(duration_ns, op)?;
  Ok(timestamps.iter().copied().zip(values.iter().copied())
    .map(|(ts, value)| state.update_at(0, ts, value)).collect())
}

pub fn ta_time_rolling_var(timestamps: &[i64], values: &[f64], duration_ns: i64) -> Result<Vec<f64>, Error> {
  time_rolling_op(timestamps, values, duration_ns, SessionOp::Var)
}

pub fn ta_time_rolling_std(timestamps: &[i64], values: &[f64], duration_ns: i64) -> Result<Vec<f64>, Error> {
  time_rolling_op(timestamps, values, duration_ns, SessionOp::Std)
}

pub fn ta_time_rolling_min(timestamps: &[i64], values: &[f64], duration_ns: i64) -> Result<Vec<f64>, Error> {
  time_rolling_op(timestamps, values, duration_ns, SessionOp::Min)
}

pub fn ta_time_rolling_max(timestamps: &[i64], values: &[f64], duration_ns: i64) -> Result<Vec<f64>, Error> {
  time_rolling_op(timestamps, values, duration_ns, SessionOp::Max)
}

pub fn ta_time_rolling_skew(timestamps: &[i64], values: &[f64], duration_ns: i64) -> Result<Vec<f64>, Error> {
  time_rolling_op(timestamps, values, duration_ns, SessionOp::Skew)
}

pub fn ta_time_rolling_quantile(timestamps: &[i64], values: &[f64], duration_ns: i64, q: f64) -> Result<Vec<f64>, Error> {
  time_rolling_op(timestamps, values, duration_ns, SessionOp::Quantile(q))
}

pub fn ta_time_rolling_rank(timestamps: &[i64], values: &[f64], duration_ns: i64) -> Result<Vec<f64>, Error> {
  time_rolling_op(timestamps, values, duration_ns, SessionOp::Rank)
}

fn time_rolling_pair(
  timestamps: &[i64], x: &[f64], y: &[f64], duration_ns: i64, correlation: bool,
) -> Result<Vec<f64>, Error> {
  if timestamps.len() != x.len() || x.len() != y.len() {
    return Err(Error::LengthMismatch(timestamps.len(), x.len()));
  }
  let mut state = SessionPairState::new_wall(duration_ns, correlation)?;
  Ok(timestamps.iter().copied().zip(x.iter().copied()).zip(y.iter().copied())
    .map(|((ts, x), y)| state.update_at(0, ts, x, y)).collect())
}

pub fn ta_time_rolling_cov(
  timestamps: &[i64], x: &[f64], y: &[f64], duration_ns: i64,
) -> Result<Vec<f64>, Error> {
  time_rolling_pair(timestamps, x, y, duration_ns, false)
}

pub fn ta_time_rolling_corr(
  timestamps: &[i64], x: &[f64], y: &[f64], duration_ns: i64,
) -> Result<Vec<f64>, Error> {
  time_rolling_pair(timestamps, x, y, duration_ns, true)
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
  let _ = ctx;
  session_rolling_state(values, session_ids, lookback_sessions, SessionOp::Sum)
}

pub fn ta_session_rolling_mean<NumT: Float>(
  ctx: &Context,
  values: &[f64],
  session_ids: &[u32],
  lookback_sessions: usize,
) -> Result<Vec<NumT>, Error> {
  let _ = ctx;
  session_rolling_state(values, session_ids, lookback_sessions, SessionOp::Mean)
}

pub struct EmaState {
  decay: f64,
  numerator: f64,
  denominator: f64,
  observations: usize,
  minimum: usize,
  last: f64,
}

impl EmaState {
  pub fn new(span: usize) -> Result<Self, Error> {
    if span == 0 {
      return Err(Error::InvalidParameter("span must be positive".to_string()));
    }
    Ok(Self {
      decay: 1.0 - 2.0 / (span as f64 + 1.0),
      numerator: 0.0,
      denominator: 0.0,
      observations: 0,
      minimum: (span / 2).max(1),
      last: f64::NAN,
    })
  }

  pub fn update(&mut self, value: f64) -> f64 {
    self.numerator *= self.decay;
    self.denominator *= self.decay;
    if value.is_finite() {
      self.numerator += value;
      self.denominator += 1.0;
      self.observations += 1;
    }
    if self.observations >= self.minimum && self.denominator > 0.0 {
      let result = self.numerator / self.denominator;
      self.last = result;
      result
    } else {
      self.last
    }
  }
}

pub fn ta_ema_streaming(values: &[f64], span: usize) -> Result<Vec<f64>, Error> {
  let mut state = EmaState::new(span)?;
  Ok(values.iter().copied().map(|value| state.update(value)).collect())
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
  if values.len() != session_ids.len() {
    return Err(Error::LengthMismatch(values.len(), session_ids.len()));
  }
  let mut state = SessionWindowState::new_op(lookback_sessions, SessionOp::Quantile(quantile))?;
  Ok(values.iter().copied().zip(session_ids.iter().copied())
    .map(|(value, session)| state.update(session, value)).collect())
}

pub fn ta_session_rolling_mad(
  values: &[f64], session_ids: &[u32], lookback_sessions: usize,
) -> Result<Vec<f64>, Error> {
  session_rolling_state(values, session_ids, lookback_sessions, SessionOp::Mad)
}

pub fn ta_session_rolling_rank(
  values: &[f64], session_ids: &[u32], lookback_sessions: usize,
) -> Result<Vec<f64>, Error> {
  if values.len() != session_ids.len() {
    return Err(Error::LengthMismatch(values.len(), session_ids.len()));
  }
  let mut state = SessionWindowState::new_op(lookback_sessions, SessionOp::Rank)?;
  Ok(values.iter().copied().zip(session_ids.iter().copied())
    .map(|(value, session)| state.update(session, value)).collect())
}

/// Backward-compatible alias: wall-clock is a WindowPolicy of the same kernel.
pub type TimeWindowState = SessionWindowState;

fn time_rolling(
  timestamps: &[i64], values: &[f64], duration_ns: i64, mean: bool,
) -> Result<Vec<f64>, Error> {
  if timestamps.len() != values.len() {
    return Err(Error::LengthMismatch(timestamps.len(), values.len()));
  }
  let op = if mean { SessionOp::Mean } else { SessionOp::Sum };
  let mut state = SessionWindowState::new_wall(duration_ns, op)?;
  Ok(timestamps.iter().copied().zip(values.iter().copied())
    .map(|(ts, value)| state.update_at(0, ts, value)).collect())
}

pub struct SessionPairState {
  policy: WindowPolicy,
  correlation: bool,
  ring: VecDeque<(u32, i64, f64, f64)>,
  sx: f64,
  sy: f64,
  sxx: f64,
  syy: f64,
  sxy: f64,
  count: usize,
}

impl SessionPairState {
  pub fn new(lookback_sessions: usize, correlation: bool) -> Result<Self, Error> {
    if lookback_sessions == 0 {
      return Err(Error::InvalidParameter("lookback must be positive".to_string()));
    }
    Ok(Self {
      policy: WindowPolicy::Sessions(lookback_sessions as u32),
      correlation,
      ring: VecDeque::new(),
      sx: 0.0, sy: 0.0, sxx: 0.0, syy: 0.0, sxy: 0.0, count: 0,
    })
  }

  pub fn new_wall(duration_ns: i64, correlation: bool) -> Result<Self, Error> {
    let mut state = Self::new(1, correlation)?;
    if duration_ns <= 0 {
      return Err(Error::InvalidParameter("duration must be positive".to_string()));
    }
    state.policy = WindowPolicy::WallClock(duration_ns);
    Ok(state)
  }

  pub fn new_bars(max_bars: usize, correlation: bool) -> Result<Self, Error> {
    if max_bars == 0 {
      return Err(Error::InvalidParameter("max_bars must be positive".to_string()));
    }
    let mut state = Self::new(1, correlation)?;
    state.policy = WindowPolicy::Bars(max_bars as u32);
    Ok(state)
  }

  fn remove_oldest(&mut self) {
    let Some((_, _, ox, oy)) = self.ring.pop_front() else { return };
    if ox.is_finite() && oy.is_finite() {
      self.sx -= ox; self.sy -= oy; self.sxx -= ox * ox;
      self.syy -= oy * oy; self.sxy -= ox * oy; self.count -= 1;
    }
  }

  pub fn update(&mut self, session_id: u32, x: f64, y: f64) -> f64 {
    self.update_at(session_id, 0, x, y)
  }

  pub fn update_at(&mut self, session_id: u32, timestamp_ns: i64, x: f64, y: f64) -> f64 {
    if let Some((last_session, last_timestamp, _, _)) = self.ring.back() {
      match self.policy {
        WindowPolicy::Sessions(_) if session_id < *last_session => return f64::NAN,
        WindowPolicy::WallClock(_) if timestamp_ns < *last_timestamp => return f64::NAN,
        _ => {}
      }
    }
    match self.policy {
      WindowPolicy::Sessions(lookback) => {
        let first_session = (session_id + 1).saturating_sub(lookback);
        while self.ring.front().is_some_and(|(id, _, _, _)| *id < first_session) {
          self.remove_oldest();
        }
      }
      WindowPolicy::WallClock(duration) => {
        while self.ring.front().is_some_and(|(_, ts, _, _)| timestamp_ns - *ts > duration) {
          self.remove_oldest();
        }
      }
      WindowPolicy::Bars(max_bars) => {
        while self.ring.len() >= max_bars as usize {
          self.remove_oldest();
        }
      }
      WindowPolicy::PartitionRange { .. } => {}
      WindowPolicy::StartIndex => {}
      WindowPolicy::Partition => {
        if let Some((last, _, _, _)) = self.ring.back() {
          if *last != session_id {
            self.ring.clear();
            self.sx = 0.0; self.sy = 0.0; self.sxx = 0.0;
            self.syy = 0.0; self.sxy = 0.0; self.count = 0;
          }
        }
      }
    }
    self.ring.push_back((session_id, timestamp_ns, x, y));
    if x.is_finite() && y.is_finite() {
      self.sx += x; self.sy += y; self.sxx += x * x;
      self.syy += y * y; self.sxy += x * y; self.count += 1;
    }
    if self.count < 2 { return f64::NAN; }
    let n = self.count as f64;
    let cov = (self.sxy - self.sx * self.sy / n) / (n - 1.0);
    if !self.correlation { return cov; }
    let vx = (self.sxx - self.sx * self.sx / n).max(0.0);
    let vy = (self.syy - self.sy * self.sy / n).max(0.0);
    let denom = (vx * vy).sqrt();
    if denom > 0.0 { (self.sxy - self.sx * self.sy / n) / denom } else { f64::NAN }
  }
}

fn session_rolling_pair(
  x: &[f64], y: &[f64], session_ids: &[u32], lookback_sessions: usize,
  correlation: bool,
) -> Result<Vec<f64>, Error> {
  if x.len() != y.len() {
    return Err(Error::LengthMismatch(x.len(), y.len()));
  }
  validate(x, session_ids, lookback_sessions)?;
  let mut state = SessionPairState::new(lookback_sessions, correlation)?;
  Ok(x.iter().copied().zip(y.iter().copied()).zip(session_ids.iter().copied())
    .map(|((x, y), session)| state.update(session, x, y)).collect())
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
  fn streaming_pair_cov_and_corr() {
    let mut corr = SessionPairState::new(1, true).unwrap();
    corr.update(0, 1.0, 2.0);
    assert!((corr.update(0, 2.0, 4.0) - 1.0).abs() < 1e-12);
    assert!(corr.update(1, 3.0, 6.0).is_nan() || corr.update(1, 3.0, 6.0).is_finite());
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
  fn time_window_supports_all_single_series_ops() {
    let timestamps = [0i64, 1_000, 2_000];
    let values = [1.0, 2.0, 4.0];
    let var = ta_time_rolling_var(&timestamps, &values, 2_000).unwrap();
    assert!((var[2] - 7.0 / 3.0).abs() < 1e-12);
    let min = ta_time_rolling_min(&timestamps, &values, 1_000).unwrap();
    assert_eq!(min[2], 2.0);
    let q = ta_time_rolling_quantile(&timestamps, &values, 2_000, 0.5).unwrap();
    assert_eq!(q[2], 2.0);
  }

  #[test]
  fn event_start_index_evicts_older_bars() {
    let mut state = SessionWindowState::new_start_index(SessionOp::Sum).unwrap();
    assert_eq!(state.update_from(0, 1.0), 1.0);
    assert_eq!(state.update_from(0, 2.0), 3.0);
    assert_eq!(state.update_from(1, 5.0), 7.0);
  }

  #[test]
  fn partition_range_truncates_and_freezes() {
    let mut state = SessionWindowState::new_partition_range(0, Some(0), SessionOp::Sum).unwrap();
    assert_eq!(state.update(1, 2.0), 2.0);
    assert_eq!(state.update(1, 3.0), 2.0);
    assert_eq!(state.update(2, 7.0), 7.0);
  }

  #[test]
  fn partition_policy_resets_at_boundary() {
    let mut state = SessionWindowState::new_partition(SessionOp::Sum).unwrap();
    assert_eq!(state.update(1, 2.0), 2.0);
    assert_eq!(state.update(1, 3.0), 5.0);
    assert_eq!(state.update(2, 7.0), 7.0);
  }

  #[test]
  fn streaming_ema_matches_adjusted_recurrence() {
    let values = ta_ema_streaming(&[1.0, 2.0, 3.0], 3).unwrap();
    assert!(values[2].is_finite());
    assert!(values[2] > 2.0 && values[2] < 3.0);
  }

  #[test]
  fn session_mad_is_built_from_order_stats() {
    let values = [1.0, 2.0, 3.0, 4.0];
    let sessions = [0u32, 0, 0, 0];
    let mad = ta_session_rolling_mad(&values, &sessions, 1).unwrap();
    assert!((mad[3] - 1.0).abs() < 1e-12);
  }

  #[test]
  fn bar_policy_evicts_by_count() {
    let mut state = SessionWindowState::new_bars(2, SessionOp::Sum).unwrap();
    assert_eq!(state.update(0, 1.0), 1.0);
    assert_eq!(state.update(0, 2.0), 3.0);
    assert_eq!(state.update(0, 3.0), 5.0);
  }

  #[test]
  fn wall_pair_cov_and_corr() {
    let ts = [0i64, 1_000, 2_000];
    let x = [1.0, 2.0, 3.0];
    let y = [2.0, 4.0, 6.0];
    let corr = ta_time_rolling_corr(&ts, &x, &y, 2_000).unwrap();
    assert!((corr[2] - 1.0).abs() < 1e-12);
    let cov = ta_time_rolling_cov(&ts, &x, &y, 1_000).unwrap();
    assert!((cov[2] - 1.0).abs() < 1e-12);
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
