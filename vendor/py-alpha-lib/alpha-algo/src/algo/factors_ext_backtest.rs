// Copyright 2026 MSD-RS Project LiJia
// SPDX-License-Identifier: BSD-2-Clause

use num_traits::Float;

use crate::algo::{Context, Error};

/// Batch searchsorted-left over ragged sorted index arrays.
///
/// ``indices`` is the concatenation of per-product index values (relative to
/// ``query``); ``offsets`` has P+1 entries. For each product the first position
/// with index >= query is returned, or -1 when the product has no such bar.
/// The caller adds the execution delay and constructs timestamps.
pub fn ta_ft_exec_positions<NumT: Float + Send + Sync>(
  _ctx: &Context,
  r: &mut [NumT],
  indices: &[NumT],
  offsets: &[NumT],
  query: NumT,
  _delay: usize,
) -> Result<(), Error> {
  if r.len() != indices.len() {
    return Err(Error::LengthMismatch(r.len(), indices.len()));
  }
  let products = offsets.len().saturating_sub(1);
  for product in 0..products {
    let start = offsets[product].to_usize().unwrap_or(0);
    let end = offsets[product + 1].to_usize().unwrap_or(start);
    if start > end || end > indices.len() {
      continue;
    }
    let mut low = start;
    let mut high = end;
    while low < high {
      let mid = (low + high) / 2;
      if indices[mid] < query {
        low = mid + 1;
      } else {
        high = mid;
      }
    }
    let value = if low >= end {
      NumT::from(-1i32).unwrap()
    } else {
      NumT::from(low - start).unwrap()
    };
    for offset in start..end {
      r[offset] = value;
    }
  }
  Ok(())
}

/// Batch execution timestamp resolution for ragged sorted index arrays.
///
/// ``indices``/``offsets`` are relative-ns ragged arrays (query = 0).
/// ``mode`` 0 returns the price timestamp, 1 the visibility timestamp.
pub fn ta_ft_exec_schedule_ts<NumT: Float + Send + Sync>(
  _ctx: &Context,
  r: &mut [NumT],
  indices: &[NumT],
  offsets: &[NumT],
  delay: usize,
  freq: NumT,
  open_delay: NumT,
  end_delay: NumT,
  open_basis: usize,
  mode: usize,
) -> Result<(), Error> {
  if r.len() != indices.len() {
    return Err(Error::LengthMismatch(r.len(), indices.len()));
  }
  let products = offsets.len().saturating_sub(1);
  for product in 0..products {
    let start = offsets[product].to_usize().unwrap_or(0);
    let end = offsets[product + 1].to_usize().unwrap_or(start);
    if start >= end || end > indices.len() {
      continue;
    }
    let mut low = start;
    let mut high = end;
    while low < high {
      let mid = (low + high) / 2;
      if indices[mid] < NumT::zero() { low = mid + 1 } else { high = mid }
    }
    let length = end - start;
    let price_pos = (low - start) + delay;
    let value = if price_pos >= length {
      NumT::nan()
    } else if mode == 0 {
      indices[start + price_pos]
    } else if open_basis != 0 {
      if price_pos == 0 {
        NumT::nan()
      } else {
        let previous = indices[start + price_pos - 1] + open_delay;
        let bar_open = if freq > NumT::zero() {
          indices[start + price_pos] - freq + open_delay
        } else {
          previous
        };
        if previous > bar_open { previous } else { bar_open }
      }
    } else {
      indices[start + price_pos] + end_delay
    };
    for offset in start..end {
      r[offset] = value;
    }
  }
  Ok(())
}

/// Stable ordering for backtest events: (timestamp, kind, sequence, push index).
///
/// Output[i] is the original position of the i-th event in dispatch order.
pub fn ta_ft_event_order<NumT: Float + Send + Sync>(
  _ctx: &Context,
  r: &mut [NumT],
  timestamps: &[NumT],
  kinds: &[NumT],
  sequences: &[NumT],
) -> Result<(), Error> {
  if r.len() != timestamps.len() || r.len() != kinds.len() || r.len() != sequences.len() {
    return Err(Error::LengthMismatch(r.len(), timestamps.len()));
  }
  let mut order: Vec<usize> = (0..timestamps.len()).collect();
  order.sort_by(|&left, &right| {
    timestamps[left]
      .partial_cmp(&timestamps[right])
      .unwrap_or(std::cmp::Ordering::Equal)
      .then_with(|| kinds[left].partial_cmp(&kinds[right]).unwrap_or(std::cmp::Ordering::Equal))
      .then_with(|| sequences[left].partial_cmp(&sequences[right]).unwrap_or(std::cmp::Ordering::Equal))
      .then_with(|| left.cmp(&right))
  });
  for (position, original) in order.into_iter().enumerate() {
    r[position] = NumT::from(original).unwrap();
  }
  Ok(())
}

/// Bar visibility timestamps relative to the first bar.
///
/// ``indices`` are nanosecond offsets from the first bar.  ``open_basis``
/// selects next-bar OPEN visibility; otherwise bar-end visibility applies.
pub fn ta_ft_bar_visibility<NumT: Float + Send + Sync>(
  _ctx: &Context,
  r: &mut [NumT],
  indices: &[NumT],
  open_basis: usize,
  open_delay: NumT,
  end_delay: NumT,
  freq: NumT,
) -> Result<(), Error> {
  if r.len() != indices.len() {
    return Err(Error::LengthMismatch(r.len(), indices.len()));
  }
  for position in 0..indices.len() {
    r[position] = if open_basis != 0 {
      if position == 0 {
        NumT::nan()
      } else {
        let previous = indices[position - 1] + open_delay;
        let bar_open = if freq > NumT::zero() {
          indices[position] - freq + open_delay
        } else {
          previous
        };
        if previous > bar_open { previous } else { bar_open }
      }
    } else {
      indices[position] + end_delay
    };
  }
  Ok(())
}

/// Sequential average-cost fill chain.
///
/// Output mode 0 = running quantity after each fill, 1 = average cost,
/// 2 = realized pnl.  One call handles an entire same-product fill batch.
pub fn ta_ft_average_cost_chain<NumT: Float + Send + Sync>(
  _ctx: &Context,
  r: &mut [NumT],
  fill_qty: &[NumT],
  price: &[NumT],
  multiplier: &[NumT],
  prior_qty: NumT,
  prior_cost: NumT,
  mode: usize,
) -> Result<(), Error> {
  if r.len() != fill_qty.len()
    || r.len() != price.len()
    || r.len() != multiplier.len()
  {
    return Err(Error::LengthMismatch(r.len(), fill_qty.len()));
  }
  let epsilon = NumT::from(1e-12).unwrap();
  let mut quantity = prior_qty;
  let mut cost = prior_cost;
  for index in 0..r.len() {
    let fill = fill_qty[index];
    let fill_price = price[index];
    let scale = multiplier[index];
    let new_quantity = quantity + fill;
    let mut realized = NumT::zero();
    if quantity == NumT::zero() || (quantity > NumT::zero()) == (fill > NumT::zero()) {
      cost = if new_quantity.abs() <= epsilon {
        NumT::zero()
      } else {
        (quantity * cost + fill * fill_price) / new_quantity
      };
    } else {
      let close_abs = quantity.abs().min(fill.abs());
      realized = close_abs * (fill_price - cost) * quantity.signum() * scale;
      if new_quantity.abs() <= epsilon {
        cost = NumT::zero();
      } else if fill.abs() > quantity.abs() {
        cost = fill_price;
      }
    }
    quantity = if new_quantity.abs() <= epsilon { NumT::zero() } else { new_quantity };
    r[index] = match mode {
      0 => quantity,
      1 => cost,
      2 => realized,
      _ => NumT::nan(),
    };
  }
  Ok(())
}

/// Target-weight sizing: target = weight * equity / (price * multiplier).
///
/// mode 0 = raw target, 1 = delta target-current, 2 = delta rounded to lot.
pub fn ta_ft_target_quantities<NumT: Float + Send + Sync>(
  _ctx: &Context,
  r: &mut [NumT],
  prices: &[NumT],
  multipliers: &[NumT],
  weights: &[NumT],
  current: &[NumT],
  lot_sizes: &[NumT],
  equity: NumT,
  round_policy: usize,
  mode: usize,
) -> Result<(), Error> {
  let length = prices.len();
  if multipliers.len() != length || weights.len() != length || current.len() != length || lot_sizes.len() != length || r.len() != length {
    return Err(Error::LengthMismatch(r.len(), length));
  }
  for index in 0..length {
    let denominator = prices[index] * multipliers[index];
    let target = if denominator == NumT::zero() {
      NumT::zero()
    } else {
      weights[index] * equity / denominator
    };
    let delta = target - current[index];
    let lot = if lot_sizes[index] > NumT::zero() { lot_sizes[index] } else { NumT::one() };
    let rounded = match round_policy {
      1 => (delta / lot).round() * lot,
      2 => (delta / lot).ceil() * lot,
      _ => (delta / lot).floor() * lot,
    };
    r[index] = match mode { 0 => target, 1 => delta, 2 => rounded, _ => NumT::nan() };
  }
  Ok(())
}
