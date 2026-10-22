// Copyright 2026 MSD-RS Project LiJia
// SPDX-License-Identifier: BSD-2-Clause
//
// FactorTester fork additions: term-structure curve operators.
//
// Layout: `values` / `days` are (rows x slots) row-major flattened, one row per
// timestamp, slots ordered by contract rank (front month first). `lengths`
// holds the number of valid contracts per row. The per-row scalar result is
// replicated into every slot of that row so the Python binding can keep the
// input length; callers read `result.reshape(rows, slots)[:, 0]`.

use num_traits::Float;

use crate::algo::{Context, Error, is_normal};

fn row_value<NumT: Float>(data: &[NumT], slots: usize, row: usize, rank: usize) -> NumT {
  data[row * slots + rank]
}

fn write_row<NumT: Float>(r: &mut [NumT], slots: usize, row: usize, value: NumT) {
  for slot in 0..slots {
    r[row * slots + slot] = value;
  }
}

/// Pairwise curve op: 0 spread, 1 ratio, 2 log-ratio, 3 contango,
/// 4 annualized carry, 5 segment slope, 6 rank value.
pub fn ta_ft_curve_pair<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  values: &[NumT],
  days: &[NumT],
  lengths: &[NumT],
  near: usize,
  far: usize,
  op: usize,
) -> Result<(), Error> {
  if r.len() != values.len() || days.len() != values.len() {
    return Err(Error::LengthMismatch(r.len(), values.len()));
  }
  let rows = lengths.len();
  if rows == 0 {
    return Ok(());
  }
  let slots = values.len() / rows;
  r.fill(NumT::nan());
  let start = ctx.start(rows);
  let end = ctx.end(rows);
  for row in start..end {
    let length = lengths[row].to_usize().unwrap_or(0);
    if op == 6 {
      if length <= near {
        continue;
      }
      write_row(r, slots, row, row_value(values, slots, row, near));
      continue;
    }
    if length <= near.max(far) {
      continue;
    }
    let v_near = row_value(values, slots, row, near);
    let v_far = row_value(values, slots, row, far);
    if !is_normal(&v_near) || !is_normal(&v_far) {
      continue;
    }
    let d_near = row_value(days, slots, row, near);
    let d_far = row_value(days, slots, row, far);
    let day_diff = d_far - d_near;
    let value = match op {
      0 => v_near - v_far,
      1 => {
        if v_far == NumT::zero() { continue; } else { v_near / v_far - NumT::one() }
      }
      2 => {
        if v_near > NumT::zero() && v_far > NumT::zero() {
          (v_near / v_far).ln()
        } else {
          continue;
        }
      }
      3 => {
        if v_near == NumT::zero() { continue; } else { v_far / v_near - NumT::one() }
      }
      4 => {
        if v_far == NumT::zero() || !is_normal(&day_diff) || day_diff == NumT::zero() {
          continue;
        }
        (v_near / v_far - NumT::one()) * NumT::from(365.0).unwrap() / day_diff
      }
      5 => {
        if !is_normal(&day_diff) || day_diff == NumT::zero() {
          continue;
        }
        (v_far - v_near) / day_diff
      }
      _ => continue,
    };
    write_row(r, slots, row, value);
  }
  Ok(())
}

/// Polynomial fit over the first `depth` valid (days, value) pairs:
/// `op == 0` returns the linear coefficient, `op == 1` the quadratic one.
pub fn ta_ft_curve_fit<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  values: &[NumT],
  days: &[NumT],
  lengths: &[NumT],
  depth: usize,
  op: usize,
) -> Result<(), Error> {
  if r.len() != values.len() || days.len() != values.len() {
    return Err(Error::LengthMismatch(r.len(), values.len()));
  }
  let rows = lengths.len();
  if rows == 0 {
    return Ok(());
  }
  let slots = values.len() / rows;
  r.fill(NumT::nan());
  let start = ctx.start(rows);
  let end = ctx.end(rows);
  for row in start..end {
    let length = lengths[row].to_usize().unwrap_or(0);
    if length == 0 {
      continue;
    }
    let mut xs: Vec<NumT> = Vec::with_capacity(depth);
    let mut ys: Vec<NumT> = Vec::with_capacity(depth);
    for slot in 0..depth.min(length) {
      let x = row_value(days, slots, row, slot);
      let y = row_value(values, slots, row, slot);
      if is_normal(&x) && is_normal(&y) {
        xs.push(x);
        ys.push(y);
      }
    }
    let n = xs.len();
    let degree = if op == 0 { 1 } else { 2 };
    if n < degree + 1 {
      continue;
    }
    // Center x for conditioning, then normal equations.
    let count = NumT::from(n).unwrap();
    let mean_x = xs.iter().fold(NumT::zero(), |a, v| a + *v) / count;
    let size = degree + 1;
    let mut a = vec![vec![NumT::zero(); size]; size];
    let mut b = vec![NumT::zero(); size];
    for i in 0..n {
      let x = xs[i] - mean_x;
      let y = ys[i];
      let mut powers = [NumT::one(); 3];
      for p in 1..size {
        powers[p] = powers[p - 1] * x;
      }
      for row_a in 0..size {
        b[row_a] = b[row_a] + powers[row_a] * y;
        for col in 0..size {
          a[row_a][col] = a[row_a][col] + powers[row_a] * powers[col];
        }
      }
    }
    // Gaussian elimination with partial pivoting.
    for col in 0..size {
      let mut pivot = col;
      for row_i in col + 1..size {
        if a[row_i][col].abs() > a[pivot][col].abs() {
          pivot = row_i;
        }
      }
      if !(a[pivot][col].abs() > NumT::from(1e-18).unwrap()) {
        break;
      }
      a.swap(col, pivot);
      b.swap(col, pivot);
      let diag = a[col][col];
      for k in col..size {
        a[col][k] = a[col][k] / diag;
      }
      b[col] = b[col] / diag;
      for row_i in 0..size {
        if row_i == col {
          continue;
        }
        let factor = a[row_i][col];
        if factor == NumT::zero() {
          continue;
        }
        for k in col..size {
          a[row_i][k] = a[row_i][k] - factor * a[col][k];
        }
        b[row_i] = b[row_i] - factor * b[col];
      }
    }
    write_row(r, slots, row, b[degree]);
  }
  Ok(())
}
