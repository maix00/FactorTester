// Copyright 2026 MSD-RS Project LiJia
// SPDX-License-Identifier: BSD-2-Clause
//
// FactorTester fork additions (batch path only): rolling operators that the
// upstream crate does not provide with matching semantics. NaN is treated as
// "not observed": it is skipped in statistics while still consuming a bar.
// Warm-up is controlled by the caller through `min_count` (or by window
// position for arg-extrema, matching the FactorTester contract).

use num_traits::Float;
use rayon::prelude::*;

use crate::algo::{Context, Error, is_normal};

fn collect_window<NumT: Float>(x: &[NumT], start: usize, periods: usize) -> Vec<NumT> {
  let mut buf = Vec::with_capacity(periods);
  let win_start = start.saturating_sub(periods - 1);
  for k in win_start..=start {
    let value = x[k];
    if is_normal(&value) {
      buf.push(value);
    }
  }
  buf
}

/// Exponential moving average matching pandas `ewm(span=periods, adjust=True, ignore_na=False).mean()`.
///
/// Every bar multiplies the running numerator and denominator by `1 - alpha`
/// (missing bars included). Observed bars then add the value / unit weight;
/// missing bars only decay, and the output repeats the previous EMA value.
/// `min_count` counts observed bars, matching pandas `min_periods`.
pub fn ta_ema_adjust<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  periods: usize,
  min_count: usize,
) -> Result<(), Error> {
  if r.len() != input.len() {
    return Err(Error::LengthMismatch(r.len(), input.len()));
  }
  r.fill(NumT::nan());
  if periods == 0 {
    return Ok(());
  }
  let alpha = NumT::from(2).unwrap() / NumT::from(periods + 1).unwrap();
  let decay = NumT::one() - alpha;
  let minimum = min_count.max(1);

  r.par_chunks_mut(ctx.chunk_size(r.len()))
    .zip(input.par_chunks(ctx.chunk_size(input.len())))
    .for_each(|(r, x)| {
      let start = ctx.start(r.len());
      let end = ctx.end(r.len());
      let mut numerator = NumT::zero();
      let mut denominator = NumT::zero();
      let mut observed = 0usize;
      let mut last = NumT::nan();
      for i in start..end {
        let value = x[i];
        numerator = numerator * decay;
        denominator = denominator * decay;
        if is_normal(&value) {
          numerator = numerator + value;
          denominator = denominator + NumT::one();
          observed += 1;
          last = numerator / denominator;
        }
        if observed >= minimum {
          r[i] = last;
        }
      }
    });
  Ok(())
}

/// Rolling skewness matching pandas `rolling(periods, min_periods=min_count).skew()`.
///
/// Two-pass window computation with the bias-corrected Fisher-Pearson G1
/// formula. Fewer than three valid observations yield NaN; a zero-variance
/// window yields 0 (pandas behaviour).
pub fn ta_skew_exact<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  periods: usize,
  min_count: usize,
) -> Result<(), Error> {
  if r.len() != input.len() {
    return Err(Error::LengthMismatch(r.len(), input.len()));
  }
  r.fill(NumT::nan());
  if periods == 0 {
    return Ok(());
  }
  let minimum = min_count.max(1);

  // Sliding raw moments: O(n) per series instead of re-centering the whole
  // window at every bar. Values are centered on the first valid observation to
  // limit cancellation in the third moment.
  r.par_chunks_mut(ctx.chunk_size(r.len()))
    .zip(input.par_chunks(ctx.chunk_size(input.len())))
    .for_each(|(r, x)| {
      let start = ctx.start(r.len());
      let end = ctx.end(r.len());
      let center = x[..end]
        .iter()
        .copied()
        .find(|value| is_normal(value))
        .unwrap_or(NumT::zero());
      let mut count = 0usize;
      let mut s1 = NumT::zero();
      let mut s2 = NumT::zero();
      let mut s3 = NumT::zero();
      for i in 0..end {
        let value = x[i];
        if is_normal(&value) {
          let z = value - center;
          let z2 = z * z;
          s1 = s1 + z;
          s2 = s2 + z2;
          s3 = s3 + z2 * z;
          count += 1;
        }
        if i >= periods {
          let old = x[i - periods];
          if is_normal(&old) {
            let z = old - center;
            let z2 = z * z;
            s1 = s1 - z;
            s2 = s2 - z2;
            s3 = s3 - z2 * z;
            count -= 1;
          }
        }
        if i < start || count < minimum || count < 3 {
          continue;
        }
        let n = NumT::from(count).unwrap();
        let mean = s1 / n;
        let m2 = s2 - s1 * mean;
        if !(m2 > NumT::zero()) {
          r[i] = NumT::zero();
          continue;
        }
        let m3 = s3 - NumT::from(3).unwrap() * mean * s2
          + NumT::from(2).unwrap() * n * mean * mean * mean;
        let sample_var = m2 / (n - NumT::one());
        let std = sample_var.sqrt();
        r[i] = n / ((n - NumT::one()) * (n - NumT::from(2).unwrap()))
          * (m3 / (std * std * std));
      }
    });
  Ok(())
}

fn arg_extreme<NumT: Float>(
  window: &[NumT],
  find_max: bool,
  normalized: bool,
) -> NumT {
  let width = window.len();
  if width == 1 {
    return if is_normal(&window[0]) { NumT::zero() } else { NumT::nan() };
  }
  let mut best_position: Option<usize> = None;
  let mut best_value = NumT::nan();
  for (position, value) in window.iter().enumerate() {
    if !is_normal(value) {
      continue;
    }
    let replace = match best_position {
      None => true,
      // Ties resolve to the most recent bar, matching the FactorTester contract.
      Some(_) => {
        if find_max {
          *value >= best_value
        } else {
          *value <= best_value
        }
      }
    };
    if replace {
      best_position = Some(position);
      best_value = *value;
    }
  }
  match best_position {
    // A fully missing window keeps the neutral position 0.
    None => NumT::zero(),
    Some(position) => {
      let value = NumT::from(position).unwrap();
      if normalized {
        value / NumT::from(width - 1).unwrap()
      } else {
        value
      }
    }
  }
}

/// Rolling argmax of the trailing window.
///
/// Ties resolve to the most recent bar; a fully missing window returns the
/// neutral position 0; the first `periods - 1` bars are NaN. When `normalized`
/// is true the output is `position / (periods - 1)`.
pub fn ta_argmax<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  periods: usize,
) -> Result<(), Error> {
  arg_impl(ctx, r, input, periods, true, true)
}

/// Rolling argmax expressed as a window offset in `0..periods-1`.
pub fn ta_argmax_raw<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  periods: usize,
) -> Result<(), Error> {
  arg_impl(ctx, r, input, periods, false, true)
}

/// Rolling argmin of the trailing window; same contract as `ta_argmax`.
pub fn ta_argmin<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  periods: usize,
) -> Result<(), Error> {
  arg_impl(ctx, r, input, periods, true, false)
}

/// Rolling argmin expressed as a window offset in `0..periods-1`.
pub fn ta_argmin_raw<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  periods: usize,
) -> Result<(), Error> {
  arg_impl(ctx, r, input, periods, false, false)
}

fn arg_impl<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  periods: usize,
  normalized: bool,
  find_max: bool,
) -> Result<(), Error> {
  if r.len() != input.len() {
    return Err(Error::LengthMismatch(r.len(), input.len()));
  }
  r.fill(NumT::nan());
  if periods == 0 {
    return Ok(());
  }
  let warmup = periods.saturating_sub(1);

  r.par_chunks_mut(ctx.chunk_size(r.len()))
    .zip(input.par_chunks(ctx.chunk_size(input.len())))
    .for_each(|(r, x)| {
      let start = ctx.start(r.len());
      let end = ctx.end(r.len());
      for i in start..end {
        if i < warmup {
          continue;
        }
        let win_start = i + 1 - periods;
        r[i] = arg_extreme(&x[win_start..=i], find_max, normalized);
      }
    });
  Ok(())
}

/// Rolling quantile with linear interpolation and NaN skipping.
///
/// Matches numpy/pandas `rolling(periods, min_periods=min_count).quantile(q)`:
/// only observed values participate, and the position is `q * (n - 1)` with
/// linear interpolation between neighbours.
pub fn ta_quantile_nan<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  periods: usize,
  min_count: usize,
  q: NumT,
) -> Result<(), Error> {
  if r.len() != input.len() {
    return Err(Error::LengthMismatch(r.len(), input.len()));
  }
  r.fill(NumT::nan());
  if periods == 0 || !(q >= NumT::zero() && q <= NumT::one()) {
    return Ok(());
  }
  let minimum = min_count.max(1).min(periods);

  // Sliding-window order statistics: coordinate-compressed values + Fenwick
  // counts. O(n log n) per series instead of sorting the whole window at every
  // bar (the previous implementation was O(n * w log w)).
  r.par_chunks_mut(ctx.chunk_size(r.len()))
    .zip(input.par_chunks(ctx.chunk_size(input.len())))
    .for_each(|(r, x)| {
      let start = ctx.start(r.len());
      let end = ctx.end(r.len());
      let mut values: Vec<NumT> = x[..end]
        .iter()
        .copied()
        .filter(|value| is_normal(value))
        .collect();
      if values.is_empty() {
        return;
      }
      values.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
      values.dedup();
      let width = values.len();
      let mut tree = vec![0i64; width + 1];
      let mut total = 0usize;
      let mut highest = 1usize;
      while highest * 2 <= width {
        highest *= 2;
      }
      fn add(tree: &mut [i64], width: usize, position: usize, delta: i64) {
        let mut index = position + 1;
        while index <= width {
          tree[index] += delta;
          index += index & index.wrapping_neg();
        }
      }
      fn kth(tree: &[i64], width: usize, highest: usize, mut k: usize) -> usize {
        let mut index = 0usize;
        let mut step = highest;
        while step > 0 {
          let next = index + step;
          if next <= width && tree[next] <= k as i64 {
            index = next;
            k -= tree[next] as usize;
          }
          step >>= 1;
        }
        index.min(width - 1)
      }
      for i in 0..end {
        let value = x[i];
        if is_normal(&value) {
          let position = values
            .binary_search_by(|probe| {
              probe
                .partial_cmp(&value)
                .unwrap_or(std::cmp::Ordering::Equal)
            })
            .unwrap_or(0);
          add(&mut tree, width, position, 1);
          total += 1;
        }
        if i >= periods {
          let old = x[i - periods];
          if is_normal(&old) {
            let position = values
              .binary_search_by(|probe| {
                probe.partial_cmp(&old).unwrap_or(std::cmp::Ordering::Equal)
              })
              .unwrap_or(0);
            add(&mut tree, width, position, -1);
            total -= 1;
          }
        }
        if i < start || total < minimum {
          continue;
        }
        let position = q * NumT::from(total - 1).unwrap();
        let lower = position.floor().to_usize().unwrap_or(0).min(total - 1);
        let upper = (lower + 1).min(total - 1);
        let fraction = position - NumT::from(lower).unwrap();
        let lower_value = values[kth(&tree, width, highest, lower)];
        let upper_value = values[kth(&tree, width, highest, upper)];
        r[i] = lower_value + (upper_value - lower_value) * fraction;
      }
    });
  Ok(())
}
