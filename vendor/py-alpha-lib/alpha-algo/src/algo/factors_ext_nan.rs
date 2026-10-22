// Copyright 2026 MSD-RS Project LiJia
// SPDX-License-Identifier: BSD-2-Clause
//
// FactorTester fork additions: NaN-aware rolling kernels.
//
// Upstream's FLAG_SKIP_NAN fills gaps with the previous observation, which does
// not match pandas (NaN is skipped and `min_periods` counts valid points).
// FactorTester expressions contain NaN from deltas, suspensions and warm-ups,
// so a per-column pandas fallback would dominate runtime. These kernels treat
// NaN as "not observed": skipped in statistics, still consuming a bar.

use num_traits::Float;
use rayon::prelude::*;

use crate::algo::{Context, Error, is_normal};

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum NanRoll {
  Mean,
  Sum,
  Var,
  Std,
  Min,
  Max,
}

struct Accum<NumT: Float> {
  sum: NumT,
  comp: NumT,
  sum_sq: NumT,
  comp_sq: NumT,
  count: usize,
}

impl<NumT: Float> Accum<NumT> {
  fn new() -> Self {
    Self {
      sum: NumT::zero(),
      comp: NumT::zero(),
      sum_sq: NumT::zero(),
      comp_sq: NumT::zero(),
      count: 0,
    }
  }

  #[inline]
  fn add(&mut self, value: NumT) {
    // 值已按 anchor 中心化，普通累加即可；补偿项保留字段但不再维护，
    // 避免 add/remove 的补偿更新不一致引入偏差。
    self.sum = self.sum + value;
    self.sum_sq = self.sum_sq + value * value;
    self.count += 1;
  }

  #[inline]
  fn remove(&mut self, value: NumT) {
    self.sum = self.sum - value;
    self.sum_sq = self.sum_sq - value * value;
    self.count = self.count.saturating_sub(1);
  }

  #[inline]
  fn total(&self) -> NumT {
    self.sum + self.comp
  }

  #[inline]
  fn total_sq(&self) -> NumT {
    self.sum_sq + self.comp_sq
  }
}

fn roll_unary<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  periods: usize,
  min_count: usize,
  kind: NanRoll,
) -> Result<(), Error> {
  if r.len() != input.len() {
    return Err(Error::LengthMismatch(r.len(), input.len()));
  }
  r.fill(NumT::nan());
  if periods == 0 {
    return Ok(());
  }
  let minimum = min_count.max(1).min(periods);

  r.par_chunks_mut(ctx.chunk_size(r.len()))
    .zip(input.par_chunks(ctx.chunk_size(input.len())))
    .for_each(|(r, x)| {
      let start = ctx.start(r.len());
      let end = ctx.end(r.len());
      match kind {
        NanRoll::Min | NanRoll::Max => {
          roll_extreme(r, x, start, end, periods, minimum, kind == NanRoll::Max);
        }
        _ => {
          let mut acc = Accum::<NumT>::new();
          let mut anchor = NumT::zero();
          let mut has_anchor = false;
          for i in start..end {
            let entering = x[i];
            if is_normal(&entering) {
              if !has_anchor {
                anchor = entering;
                has_anchor = true;
              }
              acc.add(entering - anchor);
            }
            if i >= periods {
              let leaving = x[i - periods];
              if is_normal(&leaving) {
                acc.remove(leaving - anchor);
              }
            }
            if acc.count < minimum {
              continue;
            }
            if matches!(kind, NanRoll::Var | NanRoll::Std) && acc.count < 2 {
              continue;
            }
            let count = NumT::from(acc.count).unwrap();
            r[i] = match kind {
              NanRoll::Mean => acc.total() / count + anchor,
              NanRoll::Sum => acc.total() + anchor * count,
              NanRoll::Var | NanRoll::Std => {
                let n = count;
                let mean = acc.total() / n;
                let centered = (acc.total_sq() - n * mean * mean) / (n - NumT::one());
                let variance = if centered > NumT::zero() { centered } else { NumT::zero() };
                if kind == NanRoll::Std { variance.sqrt() } else { variance }
              }
              _ => unreachable!(),
            };
          }
        }
      }
    });
  Ok(())
}

fn roll_extreme<NumT: Float>(
  r: &mut [NumT],
  x: &[NumT],
  start: usize,
  end: usize,
  periods: usize,
  minimum: usize,
  find_max: bool,
) {
  // 单调双端队列：队首是当前窗口极值，摊销 O(1)。
  let mut deque: Vec<usize> = Vec::with_capacity(periods);
  let mut head = 0usize;
  let mut valid = 0usize;
  for i in start..end {
    while deque.len() > head {
      let back = deque[deque.len() - 1];
      let back_value = x[back];
      let cur = x[i];
      let drop = if find_max { back_value <= cur } else { back_value >= cur };
      if drop {
        deque.pop();
      } else {
        break;
      }
    }
    if is_normal(&x[i]) {
      deque.push(i);
      valid += 1;
    }
    if i >= periods {
      let leaving = x[i - periods];
      if is_normal(&leaving) {
        valid -= 1;
      }
      if head < deque.len() && deque[head] == i - periods {
        head += 1;
      }
    }
    if head < deque.len() && valid >= minimum {
      r[i] = x[deque[head]];
    }
    if head > 64 {
      deque.drain(..head);
      head = 0;
    }
  }
}

/// Rolling mean that skips missing observations; NaN until `min_count` valid points.
pub fn ta_mean_nan<NumT: Float + Send + Sync>(
  ctx: &Context, r: &mut [NumT], input: &[NumT], periods: usize, min_count: usize,
) -> Result<(), Error> {
  roll_unary(ctx, r, input, periods, min_count, NanRoll::Mean)
}

/// Rolling sum that skips missing observations.
pub fn ta_sum_nan<NumT: Float + Send + Sync>(
  ctx: &Context, r: &mut [NumT], input: &[NumT], periods: usize, min_count: usize,
) -> Result<(), Error> {
  roll_unary(ctx, r, input, periods, min_count, NanRoll::Sum)
}

/// Rolling sample variance (ddof=1) that skips missing observations.
pub fn ta_var_nan<NumT: Float + Send + Sync>(
  ctx: &Context, r: &mut [NumT], input: &[NumT], periods: usize, min_count: usize,
) -> Result<(), Error> {
  roll_unary(ctx, r, input, periods, min_count, NanRoll::Var)
}

/// Rolling sample standard deviation (ddof=1) that skips missing observations.
pub fn ta_std_nan<NumT: Float + Send + Sync>(
  ctx: &Context, r: &mut [NumT], input: &[NumT], periods: usize, min_count: usize,
) -> Result<(), Error> {
  roll_unary(ctx, r, input, periods, min_count, NanRoll::Std)
}

/// Rolling minimum that skips missing observations.
pub fn ta_min_nan<NumT: Float + Send + Sync>(
  ctx: &Context, r: &mut [NumT], input: &[NumT], periods: usize, min_count: usize,
) -> Result<(), Error> {
  roll_unary(ctx, r, input, periods, min_count, NanRoll::Min)
}

/// Rolling maximum that skips missing observations.
pub fn ta_max_nan<NumT: Float + Send + Sync>(
  ctx: &Context, r: &mut [NumT], input: &[NumT], periods: usize, min_count: usize,
) -> Result<(), Error> {
  roll_unary(ctx, r, input, periods, min_count, NanRoll::Max)
}

/// Rolling correlation on pairwise-valid observations.
pub fn ta_corr_nan<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  left: &[NumT],
  right: &[NumT],
  periods: usize,
  min_count: usize,
) -> Result<(), Error> {
  pair_nan(ctx, r, left, right, periods, min_count, true)
}

/// Rolling covariance on pairwise-valid observations (ddof=1).
pub fn ta_cov_nan<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  left: &[NumT],
  right: &[NumT],
  periods: usize,
  min_count: usize,
) -> Result<(), Error> {
  pair_nan(ctx, r, left, right, periods, min_count, false)
}

fn pair_nan<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  left: &[NumT],
  right: &[NumT],
  periods: usize,
  min_count: usize,
  correlation: bool,
) -> Result<(), Error> {
  if r.len() != left.len() || left.len() != right.len() {
    return Err(Error::LengthMismatch(left.len(), right.len()));
  }
  r.fill(NumT::nan());
  if periods == 0 {
    return Ok(());
  }
  let minimum = min_count.max(1).min(periods);

  r.par_chunks_mut(ctx.chunk_size(r.len()))
    .zip(
      left
        .par_chunks(ctx.chunk_size(left.len()))
        .zip(right.par_chunks(ctx.chunk_size(right.len()))),
    )
    .for_each(|(r, (lx, rx))| {
      let start = ctx.start(r.len());
      let end = ctx.end(r.len());
      let mut sum_left = NumT::zero();
      let mut sum_right = NumT::zero();
      let mut sum_left_sq = NumT::zero();
      let mut sum_right_sq = NumT::zero();
      let mut sum_lr = NumT::zero();
      let mut count = 0usize;
      for i in start..end {
        if is_normal(&lx[i]) && is_normal(&rx[i]) {
          sum_left = sum_left + lx[i];
          sum_right = sum_right + rx[i];
          sum_left_sq = sum_left_sq + lx[i] * lx[i];
          sum_right_sq = sum_right_sq + rx[i] * rx[i];
          sum_lr = sum_lr + lx[i] * rx[i];
          count += 1;
        }
        if i >= periods {
          let out_left = lx[i - periods];
          let out_right = rx[i - periods];
          if is_normal(&out_left) && is_normal(&out_right) {
            sum_left = sum_left - out_left;
            sum_right = sum_right - out_right;
            sum_left_sq = sum_left_sq - out_left * out_left;
            sum_right_sq = sum_right_sq - out_right * out_right;
            sum_lr = sum_lr - out_left * out_right;
            count -= 1;
          }
        }
        if count < minimum {
          continue;
        }
        let n = NumT::from(count).unwrap();
        let centered_lr = sum_lr - sum_left * sum_right / n;
        if !correlation {
          r[i] = centered_lr / (n - NumT::one());
          continue;
        }
        let var_left = sum_left_sq - sum_left * sum_left / n;
        let var_right = sum_right_sq - sum_right * sum_right / n;
        if !(var_left > NumT::zero()) || !(var_right > NumT::zero()) {
          continue;
        }
        r[i] = centered_lr / (var_left * var_right).sqrt();
      }
    });
  Ok(())
}
