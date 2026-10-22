// Copyright 2026 MSD-RS Project LiJia
// SPDX-License-Identifier: BSD-2-Clause
//
// FactorTester fork additions: rolling median / MAD and OLS time-trend metrics.
// These operators exist in FactorTester but not upstream alpha-lib. Semantics
// mirror pandas rolling(window, min_periods=min_count) and the repo's
// tools/factors/expr/rolling_regression.py sufficient-statistics formulas.

use num_traits::Float;
use rayon::prelude::*;

use crate::algo::{Context, Error, is_normal};

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum LinearMetric {
  Slope,
  R2,
  TStat,
  ResidStd,
}

fn median_in_place<NumT: Float>(buf: &mut [NumT]) -> NumT {
  let n = buf.len();
  buf.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
  if n % 2 == 1 {
    buf[n / 2]
  } else {
    (buf[n / 2 - 1] + buf[n / 2]) / NumT::from(2).unwrap()
  }
}

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

/// Rolling median with an explicit minimum valid count.
pub fn ta_median<NumT: Float + Send + Sync>(
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
  let min_count = min_count.max(1).min(periods);

  r.par_chunks_mut(ctx.chunk_size(r.len()))
    .zip(input.par_chunks(ctx.chunk_size(input.len())))
    .for_each(|(r, x)| {
      let start = ctx.start(r.len());
      let end = ctx.end(r.len());
      for i in start..end {
        let mut buf = collect_window(x, i, periods);
        if buf.len() >= min_count {
          r[i] = median_in_place(&mut buf);
        }
      }
    });
  Ok(())
}

/// Rolling median absolute deviation: median(|x - median(window)|).
pub fn ta_mad<NumT: Float + Send + Sync>(
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
  let min_count = min_count.max(1).min(periods);

  r.par_chunks_mut(ctx.chunk_size(r.len()))
    .zip(input.par_chunks(ctx.chunk_size(input.len())))
    .for_each(|(r, x)| {
      let start = ctx.start(r.len());
      let end = ctx.end(r.len());
      for i in start..end {
        let mut buf = collect_window(x, i, periods);
        if buf.len() < min_count {
          continue;
        }
        let median = median_in_place(&mut buf);
        let mut deviations: Vec<NumT> = buf.iter().map(|value| (*value - median).abs()).collect();
        r[i] = median_in_place(&mut deviations);
      }
    });
  Ok(())
}

/// Rolling OLS slope against the bar index over the trailing `periods` window.
///
/// Mirrors FactorTester's sufficient-statistics implementation: only finite
/// values participate, x is the absolute bar position, and a window is
/// eligible when it has at least `max(3, min_count)` points with non-zero
/// centered x variance.
pub fn ta_linreg_slope<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  periods: usize,
  min_count: usize,
) -> Result<(), Error> {
  linreg_metric(ctx, r, input, periods, min_count, LinearMetric::Slope)
}

/// Rolling OLS R-squared against the bar index over the trailing `periods` window.
///
/// `1 - SSE/SST`; windows with zero total variance yield NaN.
pub fn ta_linreg_r2<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  periods: usize,
  min_count: usize,
) -> Result<(), Error> {
  linreg_metric(ctx, r, input, periods, min_count, LinearMetric::R2)
}

/// Rolling OLS slope t-statistic against the bar index over the trailing window.
///
/// `slope / sqrt((SSE/(n-2)) / Sxx)`; degenerate windows yield NaN.
pub fn ta_linreg_tstat<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  periods: usize,
  min_count: usize,
) -> Result<(), Error> {
  linreg_metric(ctx, r, input, periods, min_count, LinearMetric::TStat)
}

/// Rolling OLS residual standard deviation against the bar index.
///
/// `sqrt(SSE/(n-2))` over the trailing window.
pub fn ta_linreg_resid_std<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  periods: usize,
  min_count: usize,
) -> Result<(), Error> {
  linreg_metric(ctx, r, input, periods, min_count, LinearMetric::ResidStd)
}

fn linreg_metric<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  periods: usize,
  min_count: usize,
  metric: LinearMetric,
) -> Result<(), Error> {
  if r.len() != input.len() {
    return Err(Error::LengthMismatch(r.len(), input.len()));
  }
  r.fill(NumT::nan());
  if periods == 0 {
    return Ok(());
  }
  let minimum = min_count.max(3).min(periods);

  r.par_chunks_mut(ctx.chunk_size(r.len()))
    .zip(input.par_chunks(ctx.chunk_size(input.len())))
    .for_each(|(r, x)| {
      let start = ctx.start(r.len());
      let end = ctx.end(r.len());
      for i in start..end {
        let win_start = i.saturating_sub(periods - 1);
        let mut count = 0usize;
        let mut sum_x = NumT::zero();
        let mut sum_y = NumT::zero();
        let mut sum_xx = NumT::zero();
        let mut sum_yy = NumT::zero();
        let mut sum_xy = NumT::zero();
        for k in win_start..=i {
          let y = x[k];
          if !is_normal(&y) {
            continue;
          }
          let xv = NumT::from(k).unwrap();
          count += 1;
          sum_x = sum_x + xv;
          sum_y = sum_y + y;
          sum_xx = sum_xx + xv * xv;
          sum_yy = sum_yy + y * y;
          sum_xy = sum_xy + xv * y;
        }
        if count < minimum {
          continue;
        }
        let n = NumT::from(count).unwrap();
        let centered_xx = sum_xx - sum_x * sum_x / n;
        let centered_yy = sum_yy - sum_y * sum_y / n;
        let centered_xy = sum_xy - sum_x * sum_y / n;
        if !(centered_xx > NumT::zero()) {
          continue;
        }
        let slope = centered_xy / centered_xx;
        if metric == LinearMetric::Slope {
          r[i] = slope;
          continue;
        }
        let intercept = (sum_y - slope * sum_x) / n;
        let mut sse = sum_yy - intercept * sum_y - slope * sum_xy;
        if !(sse > NumT::zero()) {
          sse = NumT::zero();
        }
        match metric {
          LinearMetric::Slope => unreachable!(),
          LinearMetric::R2 => {
            if centered_yy > NumT::zero() {
              r[i] = NumT::one() - sse / centered_yy;
            }
          }
          LinearMetric::ResidStd => {
            r[i] = (sse / (n - NumT::from(2).unwrap())).sqrt();
          }
          LinearMetric::TStat => {
            let variance = sse / (n - NumT::from(2).unwrap());
            let standard_error = (variance / centered_xx).sqrt();
            if standard_error > NumT::zero() && standard_error.is_finite() {
              r[i] = slope / standard_error;
            }
          }
        }
      }
    });
  Ok(())
}
