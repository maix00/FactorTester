// Copyright 2026 MSD-RS Project LiJia
// SPDX-License-Identifier: BSD-2-Clause
//
// FactorTester fork additions: cross-sectional (per timestamp) operators.
//
// Layout matches the rest of the crate: `groups` contiguous chunks of equal
// length, i.e. flat[g * T + t]. Cross-sectional operators walk all groups at a
// fixed t, which is strided but cheap for the panel sizes FactorTester uses.
// NaN means "not observed" everywhere: it never participates in a statistic
// and is never propagated into another product's value.

use num_traits::Float;

use crate::algo::{Context, Error, is_normal};

fn layout(len: usize, groups: usize) -> (usize, usize) {
  let groups = groups.max(1);
  let rows = len / groups;
  (groups.min(len.max(1)), rows)
}

/// Copy a (N, T) panel into a (T, N) row-major buffer so each timestamp is one
/// contiguous chunk. Cross-sectional kernels follow the same recipe: transpose
/// once, process rows in parallel, transpose the result back.


fn from_rows<NumT: Float>(buffer: &[NumT], out: &mut [NumT], groups: usize, rows: usize) {
  for g in 0..groups {
    for t in 0..rows {
      out[g * rows + t] = buffer[t * groups + g];
    }
  }
}

fn average_ranks<NumT: Float>(values: &[NumT]) -> (Vec<usize>, Vec<NumT>) {
  let mut order: Vec<usize> = (0..values.len()).collect();
  order.sort_by(|a, b| {
    values[*a]
      .partial_cmp(&values[*b])
      .unwrap_or(std::cmp::Ordering::Equal)
  });
  let mut ranks = vec![NumT::nan(); values.len()];
  let mut i = 0usize;
  while i < order.len() {
    let mut j = i + 1;
    while j < order.len() && values[order[j]] == values[order[i]] {
      j += 1;
    }
    // average rank over the tie group, 1-based
    let start = NumT::from(i + 1).unwrap();
    let end = NumT::from(j).unwrap();
    let rank = (start + end) / NumT::from(2).unwrap();
    for k in i..j {
      ranks[order[k]] = rank;
    }
    i = j;
  }
  (order, ranks)
}

/// Cross-sectional percentage rank: `rank / valid_count - 0.5`.
pub fn ta_ft_rank<NumT: Float + Send + Sync>(
  ctx: &Context, r: &mut [NumT], input: &[NumT],
) -> Result<(), Error> {
  if r.len() != input.len() {
    return Err(Error::LengthMismatch(r.len(), input.len()));
  }
  r.fill(NumT::nan());
  let (groups, rows) = layout(input.len(), ctx.groups());
  if groups == 0 || rows == 0 {
    return Ok(());
  }
  // 转成 (T, N) 连续布局后按时间步并行：每个时间步只写自己那一行，无锁。
  let mut buffer = vec![NumT::nan(); groups * rows];
  for g in 0..groups {
    for t in 0..rows {
      buffer[t * groups + g] = input[g * rows + t];
    }
  }
  use rayon::prelude::*;
  buffer.par_chunks_mut(groups).for_each(|row| {
    let mut values = Vec::with_capacity(groups);
    let mut positions = Vec::with_capacity(groups);
    for g in 0..groups {
      let v = row[g];
      if is_normal(&v) {
        values.push(v);
        positions.push(g);
      }
    }
    if values.is_empty() {
      return;
    }
    let (_, ranks) = average_ranks(&values);
    let count = NumT::from(values.len()).unwrap();
    for (index, g) in positions.iter().enumerate() {
      row[*g] = ranks[index] / count - NumT::from(0.5).unwrap();
    }
  });
  for g in 0..groups {
    for t in 0..rows {
      r[g * rows + t] = buffer[t * groups + g];
    }
  }
  Ok(())
}

/// Cross-sectional percentage rank restricted to an eligibility mask.
pub fn ta_ft_rank_masked<NumT: Float + Send + Sync>(
  ctx: &Context, r: &mut [NumT], input: &[NumT], mask: &[NumT],
) -> Result<(), Error> {
  if r.len() != input.len() || mask.len() != input.len() {
    return Err(Error::LengthMismatch(r.len(), input.len()));
  }
  r.fill(NumT::nan());
  let (groups, rows) = layout(input.len(), ctx.groups());
  if groups == 0 || rows == 0 {
    return Ok(());
  }
  let mut out_buf = vec![NumT::nan(); groups * rows];
  use rayon::prelude::*;
  out_buf
    .par_chunks_mut(groups)
    .enumerate()
    .for_each(|(t, out_row)| {
      let mut values = Vec::with_capacity(groups);
      let mut positions = Vec::with_capacity(groups);
      for g in 0..groups {
        let index = g * rows + t;
        let value = input[index];
        if is_normal(&value) && mask[index] > NumT::zero() {
          values.push(value);
          positions.push(g);
        }
      }
      if values.is_empty() {
        return;
      }
      let (_, ranks) = average_ranks(&values);
      let count = NumT::from(values.len()).unwrap();
      for (index, g) in positions.iter().enumerate() {
        out_row[*g] = ranks[index] / count - NumT::from(0.5).unwrap();
      }
    });
  from_rows(&out_buf, r, groups, rows);
  Ok(())
}

/// Ordinal rank (1..n) with `tiebreak` deciding equal values; `ascending == 0`
/// ranks descending. Non-eligible entries stay NaN.
pub fn ta_ft_ordinal_rank<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  mask: &[NumT],
  tiebreak: &[NumT],
  ascending: usize,
) -> Result<(), Error> {
  if r.len() != input.len() || mask.len() != input.len() {
    return Err(Error::LengthMismatch(r.len(), input.len()));
  }
  r.fill(NumT::nan());
  let (groups, rows) = layout(input.len(), ctx.groups());
  if groups == 0 || rows == 0 {
    return Ok(());
  }
  if tiebreak.len() < groups {
    return Err(Error::LengthMismatch(tiebreak.len(), groups));
  }
  let descending = ascending == 0;
  let mut out_buf = vec![NumT::nan(); groups * rows];
  use rayon::prelude::*;
  out_buf
    .par_chunks_mut(groups)
    .enumerate()
    .for_each(|(t, out_row)| {
      let mut eligible: Vec<usize> = Vec::with_capacity(groups);
      for g in 0..groups {
        let index = g * rows + t;
        if is_normal(&input[index]) && mask[index] > NumT::zero() {
          eligible.push(g);
        }
      }
      if eligible.is_empty() {
        return;
      }
      eligible.sort_by(|a, b| {
        let va = input[*a * rows + t];
        let vb = input[*b * rows + t];
        let base = va.partial_cmp(&vb).unwrap_or(std::cmp::Ordering::Equal);
        let base = if descending { base.reverse() } else { base };
        if base == std::cmp::Ordering::Equal {
          tiebreak[*a]
            .partial_cmp(&tiebreak[*b])
            .unwrap_or(std::cmp::Ordering::Equal)
        } else {
          base
        }
      });
      for (position, g) in eligible.iter().enumerate() {
        out_row[*g] = NumT::from(position + 1).unwrap();
      }
    });
  from_rows(&out_buf, r, groups, rows);
  Ok(())
}

/// Cross-sectional z-score with sample standard deviation (ddof=1).
/// Constant rows produce 0 for observed entries, matching the pandas backend.
pub fn ta_ft_zscore<NumT: Float + Send + Sync>(
  ctx: &Context, r: &mut [NumT], input: &[NumT],
) -> Result<(), Error> {
  if r.len() != input.len() {
    return Err(Error::LengthMismatch(r.len(), input.len()));
  }
  r.fill(NumT::nan());
  let (groups, rows) = layout(input.len(), ctx.groups());
  if groups == 0 || rows == 0 {
    return Ok(());
  }
  let mut buffer = vec![NumT::nan(); groups * rows];
  for g in 0..groups {
    for t in 0..rows {
      buffer[t * groups + g] = input[g * rows + t];
    }
  }
  use rayon::prelude::*;
  buffer.par_chunks_mut(groups).for_each(|row| {
    let mut sum = NumT::zero();
    let mut count = 0usize;
    for value in row.iter() {
      if is_normal(value) {
        sum = sum + *value;
        count += 1;
      }
    }
    if count == 0 {
      return;
    }
    let n = NumT::from(count).unwrap();
    let mean = sum / n;
    if count == 1 {
      // pandas 在只有一个有效观测时 std(ddof=1) 为 NaN，z-score 整行为 NaN。
      for value in row.iter_mut() {
        if is_normal(value) {
          *value = NumT::nan();
        }
      }
      return;
    }
    let mut m2 = NumT::zero();
    for value in row.iter() {
      if is_normal(value) {
        let d = *value - mean;
        m2 = m2 + d * d;
      }
    }
    let std = (m2 / (n - NumT::one())).sqrt();
    if std.is_nan() {
      // 行内出现 ±inf 时 pandas 的 mean/std 都是 inf/NaN，整行结果为 NaN；
      // buffer 里存的是输入值，必须显式抹成 NaN。
      for value in row.iter_mut() {
        if is_normal(value) {
          *value = NumT::nan();
        }
      }
      return;
    }
    for value in row.iter_mut() {
      if is_normal(value) {
        *value = if std > NumT::zero() { (*value - mean) / std } else { NumT::zero() };
      }
    }
  });
  for g in 0..groups {
    for t in 0..rows {
      r[g * rows + t] = buffer[t * groups + g];
    }
  }
  Ok(())
}

fn pair_value<NumT: Float>(xs: &[NumT], ys: &[NumT], correlation: bool) -> Option<NumT> {
  let n = xs.len();
  if n < 2 {
    return None;
  }
  let count = NumT::from(n).unwrap();
  let mut sx = NumT::zero();
  let mut sy = NumT::zero();
  let mut sxx = NumT::zero();
  let mut syy = NumT::zero();
  let mut sxy = NumT::zero();
  for i in 0..n {
    sx = sx + xs[i];
    sy = sy + ys[i];
    sxx = sxx + xs[i] * xs[i];
    syy = syy + ys[i] * ys[i];
    sxy = sxy + xs[i] * ys[i];
  }
  finish_pair(sx, sy, sxx, syy, sxy, count, correlation)
}

fn finish_pair<NumT: Float>(
  sx: NumT,
  sy: NumT,
  sxx: NumT,
  syy: NumT,
  sxy: NumT,
  count: NumT,
  correlation: bool,
) -> Option<NumT> {
  let centered = sxy - sx * sy / count;
  if !correlation {
    let covariance = centered / (count - NumT::one());
    return covariance.is_finite().then_some(covariance);
  }
  let var_x = sxx - sx * sx / count;
  let var_y = syy - sy * sy / count;
  if !(var_x > NumT::zero()) || !(var_y > NumT::zero()) {
    return None;
  }
  let value = centered / (var_x * var_y).sqrt();
  value.is_finite().then_some(value)
}

fn pair_stat<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  left: &[NumT],
  right: &[NumT],
  correlation: bool,
  rank: bool,
) -> Result<(), Error> {
  if r.len() != left.len() || left.len() != right.len() {
    return Err(Error::LengthMismatch(left.len(), right.len()));
  }
  r.fill(NumT::nan());
  let (groups, rows) = layout(left.len(), ctx.groups());
  if groups == 0 || rows == 0 {
    return Ok(());
  }
  // 每个时间步只读输入、只写自己的输出行：读跨步、写连续，无锁并行。
  // 不做整面板转置，省掉两次 (N, T) 拷贝；Pearson/cov 单遍累加，避免逐行分配。
  let mut out_buf = vec![NumT::nan(); groups * rows];
  use rayon::prelude::*;
  out_buf
    .par_chunks_mut(groups)
    .enumerate()
    .for_each(|(t, orow)| {
      if rank {
        // Spearman：先秩化（inf 变成有限秩），再对秩做 Pearson。
        let mut xs: Vec<NumT> = Vec::with_capacity(groups);
        let mut ys: Vec<NumT> = Vec::with_capacity(groups);
        let mut positions: Vec<usize> = Vec::with_capacity(groups);
        for g in 0..groups {
          let index = g * rows + t;
          let x = left[index];
          let y = right[index];
          if is_normal(&x) && is_normal(&y) {
            xs.push(x);
            ys.push(y);
            positions.push(g);
          }
        }
        let n = xs.len();
        if n < 2 {
          return;
        }
        let (_, rx) = average_ranks(&xs);
        let (_, ry) = average_ranks(&ys);
        if let Some(value) = pair_value(&rx, &ry, correlation) {
          for position in &positions {
            orow[*position] = value;
          }
        }
        return;
      }
      // Pearson/cov：单遍累加。
      let mut n = 0usize;
      let mut sx = NumT::zero();
      let mut sy = NumT::zero();
      let mut sxx = NumT::zero();
      let mut syy = NumT::zero();
      let mut sxy = NumT::zero();
      for g in 0..groups {
        let index = g * rows + t;
        let x = left[index];
        let y = right[index];
        if is_normal(&x) && is_normal(&y) {
          n += 1;
          sx = sx + x;
          sy = sy + y;
          sxx = sxx + x * x;
          syy = syy + y * y;
          sxy = sxy + x * y;
        }
      }
      if n < 2 {
        return;
      }
      // pandas 的 notna 路径把 ±inf 当已观测，整行 Pearson/cov 因此是 NaN；
      // 内核用同一口径：累加量非有限时整行保持 NaN。
      if !(sx.is_finite()
        && sy.is_finite()
        && sxx.is_finite()
        && syy.is_finite()
        && sxy.is_finite())
      {
        return;
      }
      let count = NumT::from(n).unwrap();
      let Some(value) = finish_pair(sx, sy, sxx, syy, sxy, count, correlation) else {
        return;
      };
      for g in 0..groups {
        let index = g * rows + t;
        if is_normal(&left[index]) && is_normal(&right[index]) {
          orow[g] = value;
        }
      }
    });
  from_rows(&out_buf, r, groups, rows);
  Ok(())
}

/// Cross-sectional Pearson correlation per timestamp.
pub fn ta_ft_corr<NumT: Float + Send + Sync>(
  ctx: &Context, r: &mut [NumT], left: &[NumT], right: &[NumT],
) -> Result<(), Error> {
  pair_stat(ctx, r, left, right, true, false)
}

/// Cross-sectional covariance per timestamp (ddof=1).
pub fn ta_ft_cov<NumT: Float + Send + Sync>(
  ctx: &Context, r: &mut [NumT], left: &[NumT], right: &[NumT],
) -> Result<(), Error> {
  pair_stat(ctx, r, left, right, false, false)
}

/// Cross-sectional Spearman correlation per timestamp.
pub fn ta_ft_spearman<NumT: Float + Send + Sync>(
  ctx: &Context, r: &mut [NumT], left: &[NumT], right: &[NumT],
) -> Result<(), Error> {
  pair_stat(ctx, r, left, right, true, true)
}

/// Category-partitioned cross-sectional transform: 0 = rank, 1 = z-score,
/// 2 = demean. `category` holds one category id per group (-1 = unassigned).
pub fn ta_ft_group<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  input: &[NumT],
  mask: &[NumT],
  category: &[NumT],
  op: usize,
) -> Result<(), Error> {
  if r.len() != input.len() || mask.len() != input.len() {
    return Err(Error::LengthMismatch(r.len(), input.len()));
  }
  r.fill(NumT::nan());
  let (groups, rows) = layout(input.len(), ctx.groups());
  if groups == 0 || rows == 0 {
    return Ok(());
  }
  let max_id = category
    .iter()
    .map(|v| v.to_usize().unwrap_or(0))
    .max()
    .unwrap_or(0);
  let mut out_buf = vec![NumT::nan(); groups * rows];
  use rayon::prelude::*;
  out_buf
    .par_chunks_mut(groups)
    .enumerate()
    .for_each(|(t, row)| {
      for id in 0..=max_id {
        let mut values = Vec::new();
        let mut positions = Vec::new();
        for g in 0..groups {
          if category[g].to_usize().unwrap_or(usize::MAX) != id {
            continue;
          }
          let index = g * rows + t;
          let value = input[index];
          if is_normal(&value) && mask[index] > NumT::zero() {
            values.push(value);
            positions.push(g);
          }
        }
        if values.is_empty() {
          continue;
        }
        match op {
          0 => {
            let (_, ranks) = average_ranks(&values);
            let count = NumT::from(values.len()).unwrap();
            for (i, position) in positions.iter().enumerate() {
              row[*position] = ranks[i] / count - NumT::from(0.5).unwrap();
            }
          }
          1 => {
            if values.len() < 2 {
              continue;
            }
            let count = NumT::from(values.len()).unwrap();
            let mean = values.iter().fold(NumT::zero(), |a, v| a + *v) / count;
            let mut m2 = NumT::zero();
            for value in &values {
              let d = *value - mean;
              m2 = m2 + d * d;
            }
            let std = (m2 / (count - NumT::one())).sqrt();
            if std.is_nan() {
              // 组内含 ±inf：pandas 的组均值/标准差为 inf/NaN，整组 NaN。
              continue;
            }
            for (i, position) in positions.iter().enumerate() {
              row[*position] = if std > NumT::zero() {
                (values[i] - mean) / std
              } else {
                NumT::zero()
              };
            }
          }
          _ => {
            let count = NumT::from(values.len()).unwrap();
            let mean = values.iter().fold(NumT::zero(), |a, v| a + *v) / count;
            for (i, position) in positions.iter().enumerate() {
              row[*position] = values[i] - mean;
            }
          }
        }
      }
    });
  from_rows(&out_buf, r, groups, rows);
  Ok(())
}

/// Cross-sectional OLS residualization on up to three exposures.
pub fn ta_ft_residualize<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  signal: &[NumT],
  exposure1: &[NumT],
  exposure2: &[NumT],
  exposure3: &[NumT],
  mask: &[NumT],
  exposure_count: usize,
) -> Result<(), Error> {
  let k = exposure_count.min(3);
  if r.len() != signal.len()
    || mask.len() != signal.len()
    || exposure1.len() != signal.len()
    || (k >= 2 && exposure2.len() != signal.len())
    || (k >= 3 && exposure3.len() != signal.len())
  {
    return Err(Error::LengthMismatch(signal.len(), r.len()));
  }
  r.fill(NumT::nan());
  let (groups, rows) = layout(signal.len(), ctx.groups());
  if groups == 0 || rows == 0 {
    return Ok(());
  }
  let mut out_buf = vec![NumT::nan(); groups * rows];
  use rayon::prelude::*;
  out_buf
    .par_chunks_mut(groups)
    .enumerate()
    .for_each(|(t, orow)| {
      let mut ys: Vec<NumT> = Vec::with_capacity(groups);
      let mut rows_x: Vec<[NumT; 3]> = Vec::with_capacity(groups);
      let mut positions: Vec<usize> = Vec::with_capacity(groups);
      for g in 0..groups {
        let index = g * rows + t;
        if !(mask[index] > NumT::zero()) || !signal[index].is_finite() {
          continue;
        }
        let x1 = exposure1[index];
        if !x1.is_finite() {
          continue;
        }
        let mut values = [NumT::zero(); 3];
        values[0] = x1;
        if k >= 2 {
          if !exposure2[index].is_finite() {
            continue;
          }
          values[1] = exposure2[index];
        }
        if k >= 3 {
          if !exposure3[index].is_finite() {
            continue;
          }
          values[2] = exposure3[index];
        }
        ys.push(signal[index]);
        rows_x.push(values);
        positions.push(g);
      }
      let n = ys.len();
      if n <= k + 1 {
        return;
      }
      // normal equations for [1, x1..xk]
      let size = k + 1;
      let mut xtx = vec![vec![NumT::zero(); size]; size];
      let mut xty = vec![NumT::zero(); size];
      for (i, y) in ys.iter().enumerate() {
        // size = k + 1, so the design row needs room for up to 1 + 3 terms.
        let mut row = [NumT::zero(); 4];
        row[0] = NumT::one();
        for j in 0..k {
          row[j + 1] = rows_x[i][j];
        }
        for a in 0..size {
          xty[a] = xty[a] + row[a] * *y;
          for b in 0..size {
            xtx[a][b] = xtx[a][b] + row[a] * row[b];
          }
        }
      }
      // gaussian elimination with partial pivoting
      for col in 0..size {
        let mut pivot = col;
        for row in col + 1..size {
          if xtx[row][col].abs() > xtx[pivot][col].abs() {
            pivot = row;
          }
        }
        if !(xtx[pivot][col].abs() > NumT::from(1e-18).unwrap()) {
          continue;
        }
        xtx.swap(col, pivot);
        xty.swap(col, pivot);
        let diag = xtx[col][col];
        for b in col..size {
          xtx[col][b] = xtx[col][b] / diag;
        }
        xty[col] = xty[col] / diag;
        for row in 0..size {
          if row == col {
            continue;
          }
          let factor = xtx[row][col];
          if factor == NumT::zero() {
            continue;
          }
          for b in col..size {
            xtx[row][b] = xtx[row][b] - factor * xtx[col][b];
          }
          xty[row] = xty[row] - factor * xty[col];
        }
      }
      for (i, position) in positions.iter().enumerate() {
        let mut fitted = xty[0];
        for j in 0..k {
          fitted = fitted + xty[j + 1] * rows_x[i][j];
        }
        orow[*position] = ys[i] - fitted;
      }
    });
  from_rows(&out_buf, r, groups, rows);
  Ok(())
}
