// Copyright 2026 MSD-RS Project LiJia
// SPDX-License-Identifier: BSD-2-Clause
//
// FactorTester fork additions: batch plan executor (ADR-161 P4).
//
// A compiled plan is a flat operator table. `slots` holds every live buffer as
// `groups * rows` contiguous panels. The executor copies the input slots into
// its own storage, then runs each op in order into its destination slot. Slot
// ids come from the Python compiler, which allocates them from lifetime
// intervals, so peak memory is O(active slots) instead of O(nodes).
//
// Every op has four integer fields [code, out, a, b] and four float fields
// [window, min_count, quantile, periods]. Taking both tables as `f64` keeps the
// generated pyo3 binding simple; codes and slot ids stay exact. Elementwise ops
// follow numpy semantics (NaN propagates; `maximum/minimum` return NaN when
// either side is NaN; `sign(-0.0) == 0`).

use num_traits::Float;

use crate::algo::{
  ta_argmax, ta_argmax_raw, ta_argmin, ta_argmin_raw, ta_corr_nan, ta_cov_nan,
  ta_ema_adjust, ta_ft_group, ta_ft_ordinal_rank, ta_ft_rank, ta_ft_rank_masked,
  ta_ft_residualize, ta_ft_scope_agg, ta_ft_zscore, ta_linreg_r2, ta_linreg_resid_std, ta_linreg_slope,
  ta_linreg_tstat, ta_mad, ta_max_nan, ta_mean_nan, ta_median, ta_min_nan, ta_quantile_nan,
  ta_skew_exact, ta_std_nan, ta_sum_nan, ta_var_nan, Context, Error,
};

pub const PLAN_FILL: usize = 2;
pub const PLAN_FUSED: usize = 90;
pub const PLAN_WHERE: usize = 27;
pub const PLAN_SCOPE: usize = 80;
pub const PLAN_SHIFT: usize = 1;

pub const PLAN_NEG: usize = 10;
pub const PLAN_ABS: usize = 11;
pub const PLAN_LOG: usize = 12;
pub const PLAN_SQRT: usize = 13;
pub const PLAN_TANH: usize = 14;
pub const PLAN_EXP: usize = 15;
pub const PLAN_SIGN: usize = 16;
pub const PLAN_NOT: usize = 17;

pub const PLAN_ADD: usize = 20;
pub const PLAN_SUB: usize = 21;
pub const PLAN_MUL: usize = 22;
pub const PLAN_DIV: usize = 23;
pub const PLAN_POW: usize = 24;
pub const PLAN_MAX: usize = 25;
pub const PLAN_MIN: usize = 26;

pub const PLAN_GT: usize = 100;
pub const PLAN_LT: usize = 101;
pub const PLAN_GE: usize = 102;
pub const PLAN_LE: usize = 103;
pub const PLAN_EQ: usize = 104;
pub const PLAN_NE: usize = 105;
pub const PLAN_AND: usize = 106;
pub const PLAN_OR: usize = 107;

pub const PLAN_MEAN: usize = 30;
pub const PLAN_STD: usize = 31;
pub const PLAN_VAR: usize = 32;
pub const PLAN_ROLL_MIN: usize = 33;
pub const PLAN_ROLL_MAX: usize = 34;
pub const PLAN_SUM: usize = 35;
pub const PLAN_MEDIAN: usize = 36;
pub const PLAN_MAD: usize = 37;
pub const PLAN_SKEW: usize = 38;
pub const PLAN_EMA: usize = 39;
pub const PLAN_QUANTILE: usize = 40;
pub const PLAN_LINREG_SLOPE: usize = 41;
pub const PLAN_LINREG_R2: usize = 42;
pub const PLAN_LINREG_TSTAT: usize = 43;
pub const PLAN_LINREG_RESID_STD: usize = 44;
pub const PLAN_ARGMAX: usize = 45;
pub const PLAN_ARGMAX_RAW: usize = 46;
pub const PLAN_ARGMIN: usize = 47;
pub const PLAN_ARGMIN_RAW: usize = 48;

pub const PLAN_CORR: usize = 60;
pub const PLAN_COV: usize = 61;

pub const PLAN_RANK: usize = 70;
pub const PLAN_RANK_MASKED: usize = 71;
pub const PLAN_ZSCORE: usize = 72;
pub const PLAN_ORDINAL: usize = 73;
pub const PLAN_GROUP: usize = 74;
pub const PLAN_RESIDUALIZE_1: usize = 75;
pub const PLAN_RESIDUALIZE_2: usize = 76;
pub const PLAN_RESIDUALIZE_3: usize = 77;

/// One operand of an elementwise op: either a slot panel or an immediate.
enum PlanOperand<'a, NumT: Float> {
  Slot(&'a [NumT]),
  Scalar(NumT),
}

impl<NumT: Float> PlanOperand<'_, NumT> {
  #[inline]
  fn at(&self, index: usize) -> NumT {
    match self {
      PlanOperand::Slot(values) => values[index],
      PlanOperand::Scalar(value) => *value,
    }
  }

  fn slot(&self) -> Result<&[NumT], Error> {
    match self {
      PlanOperand::Slot(values) => Ok(values),
      PlanOperand::Scalar(_) => {
        Err(Error::InvalidParameter("kernel operand must be a slot".into()))
      }
    }
  }

  fn slots_ref(&self) -> Option<&[NumT]> {
    match self {
      PlanOperand::Slot(values) => Some(values),
      PlanOperand::Scalar(_) => None,
    }
  }
}

fn panel_layout(len: usize, groups: usize) -> (usize, usize) {
  let groups = groups.max(1);
  (groups.min(len.max(1)), len / groups.max(1))
}

fn plan_shift<NumT: Float>(
  out: &mut [NumT], input: &[NumT], groups: usize, rows: usize, periods: i64,
) -> Result<(), Error> {
  if out.len() != input.len() {
    return Err(Error::LengthMismatch(out.len(), input.len()));
  }
  if periods == 0 {
    out.copy_from_slice(input);
    return Ok(());
  }
  out.fill(NumT::nan());
  for g in 0..groups {
    for t in 0..rows {
      let source = t as i64 - periods;
      if source >= 0 && (source as usize) < rows {
        out[g * rows + t] = input[g * rows + source as usize];
      }
    }
  }
  Ok(())
}

fn unary_loop<NumT: Float, F: Fn(NumT) -> NumT>(
  out: &mut [NumT], input: &PlanOperand<'_, NumT>, operation: F,
) {
  match input {
    PlanOperand::Slot(values) => {
      for index in 0..out.len() {
        out[index] = operation(values[index]);
      }
    }
    PlanOperand::Scalar(value) => {
      let value = *value;
      out.fill(operation(value));
    }
  }
}

fn binary_loop<NumT: Float, F: Fn(NumT, NumT) -> NumT>(
  out: &mut [NumT],
  a: &PlanOperand<'_, NumT>,
  b: &PlanOperand<'_, NumT>,
  operation: F,
) {
  match (a, b) {
    (PlanOperand::Slot(left), PlanOperand::Slot(right)) => {
      for index in 0..out.len() {
        out[index] = operation(left[index], right[index]);
      }
    }
    (PlanOperand::Slot(left), PlanOperand::Scalar(right)) => {
      let right = *right;
      for index in 0..out.len() {
        out[index] = operation(left[index], right);
      }
    }
    (PlanOperand::Scalar(left), PlanOperand::Slot(right)) => {
      let left = *left;
      for index in 0..out.len() {
        out[index] = operation(left, right[index]);
      }
    }
    (PlanOperand::Scalar(left), PlanOperand::Scalar(right)) => {
      out.fill(operation(*left, *right));
    }
  }
}

fn plan_where<NumT: Float>(
  out: &mut [NumT],
  condition: &PlanOperand<'_, NumT>,
  true_value: &PlanOperand<'_, NumT>,
  false_value: &PlanOperand<'_, NumT>,
) {
  match (condition, true_value, false_value) {
    (PlanOperand::Slot(cond), PlanOperand::Slot(left), PlanOperand::Slot(right)) => {
      for index in 0..out.len() {
        out[index] = if cond[index] != NumT::zero() {
          left[index]
        } else {
          right[index]
        };
      }
    }
    _ => {
      for index in 0..out.len() {
        out[index] = if condition.at(index) != NumT::zero() {
          true_value.at(index)
        } else {
          false_value.at(index)
        };
      }
    }
  }
}

fn plan_unary<NumT: Float>(
  code: usize, out: &mut [NumT], input: &PlanOperand<'_, NumT>,
) -> Result<(), Error> {
  match code {
    PLAN_NEG => unary_loop(out, input, |value| -value),
    PLAN_ABS => unary_loop(out, input, |value| value.abs()),
    PLAN_LOG => unary_loop(out, input, |value| value.ln()),
    PLAN_SQRT => unary_loop(out, input, |value| value.sqrt()),
    PLAN_TANH => unary_loop(out, input, |value| value.tanh()),
    PLAN_EXP => unary_loop(out, input, |value| value.exp()),
    PLAN_SIGN => unary_loop(out, input, |value| {
      if value.is_nan() {
        NumT::nan()
      } else if value > NumT::zero() {
        NumT::one()
      } else if value < NumT::zero() {
        -NumT::one()
      } else {
        NumT::zero()
      }
    }),
    // numpy.logical_not: NaN is truthy, so `not NaN == 0`.
    PLAN_NOT => unary_loop(out, input, |value| {
      if value != NumT::zero() {
        NumT::zero()
      } else {
        NumT::one()
      }
    }),
    _ => return Err(Error::InvalidParameter(format!("unknown unary plan op {code}"))),
  }
  Ok(())
}

fn bool_value<NumT: Float>(value: bool) -> NumT {
  if value {
    NumT::one()
  } else {
    NumT::zero()
  }
}

fn plan_binary<NumT: Float>(
  code: usize,
  out: &mut [NumT],
  a: &PlanOperand<'_, NumT>,
  b: &PlanOperand<'_, NumT>,
) -> Result<(), Error> {
  match code {
    PLAN_ADD => binary_loop(out, a, b, |left, right| left + right),
    PLAN_SUB => binary_loop(out, a, b, |left, right| left - right),
    PLAN_MUL => binary_loop(out, a, b, |left, right| left * right),
    PLAN_DIV => binary_loop(out, a, b, |left, right| left / right),
    PLAN_POW => binary_loop(out, a, b, |left, right| left.powf(right)),
    // numpy.maximum/minimum propagate NaN instead of ignoring it.
    PLAN_MAX => binary_loop(out, a, b, |left, right| {
      if left.is_nan() || right.is_nan() {
        NumT::nan()
      } else {
        left.max(right)
      }
    }),
    PLAN_MIN => binary_loop(out, a, b, |left, right| {
      if left.is_nan() || right.is_nan() {
        NumT::nan()
      } else {
        left.min(right)
      }
    }),
    // Comparison/logical ops mirror numpy: NaN comparisons are false (except !=),
    // and logical ops treat nonzero (including NaN) as true.
    PLAN_GT => binary_loop(out, a, b, |left, right| bool_value(left > right)),
    PLAN_LT => binary_loop(out, a, b, |left, right| bool_value(left < right)),
    PLAN_GE => binary_loop(out, a, b, |left, right| bool_value(left >= right)),
    PLAN_LE => binary_loop(out, a, b, |left, right| bool_value(left <= right)),
    PLAN_EQ => binary_loop(out, a, b, |left, right| bool_value(left == right)),
    PLAN_NE => binary_loop(out, a, b, |left, right| bool_value(left != right)),
    PLAN_AND => binary_loop(out, a, b, |left, right| {
      bool_value(left != NumT::zero() && right != NumT::zero())
    }),
    PLAN_OR => binary_loop(out, a, b, |left, right| {
      bool_value(left != NumT::zero() || right != NumT::zero())
    }),
    _ => return Err(Error::InvalidParameter(format!("unknown binary plan op {code}"))),
  }
  Ok(())
}

fn rolling_op<NumT: Float + Send + Sync>(
  code: usize,
  ctx: &Context,
  out: &mut [NumT],
  a: &[NumT],
  b: &[NumT],
  window: usize,
  min_count: usize,
  quantile: NumT,
) -> Result<(), Error> {
  match code {
    PLAN_MEAN => ta_mean_nan(ctx, out, a, window, min_count),
    PLAN_STD => ta_std_nan(ctx, out, a, window, min_count),
    PLAN_VAR => ta_var_nan(ctx, out, a, window, min_count),
    PLAN_ROLL_MIN => ta_min_nan(ctx, out, a, window, min_count),
    PLAN_ROLL_MAX => ta_max_nan(ctx, out, a, window, min_count),
    PLAN_SUM => ta_sum_nan(ctx, out, a, window, min_count),
    PLAN_MEDIAN => ta_median(ctx, out, a, window, min_count),
    PLAN_MAD => ta_mad(ctx, out, a, window, min_count),
    PLAN_SKEW => ta_skew_exact(ctx, out, a, window, min_count),
    PLAN_EMA => ta_ema_adjust(ctx, out, a, window, min_count),
    PLAN_QUANTILE => ta_quantile_nan(ctx, out, a, window, min_count, quantile),
    PLAN_LINREG_SLOPE => ta_linreg_slope(ctx, out, a, window, min_count),
    PLAN_LINREG_R2 => ta_linreg_r2(ctx, out, a, window, min_count),
    PLAN_LINREG_TSTAT => ta_linreg_tstat(ctx, out, a, window, min_count),
    PLAN_LINREG_RESID_STD => ta_linreg_resid_std(ctx, out, a, window, min_count),
    PLAN_ARGMAX => ta_argmax(ctx, out, a, window),
    PLAN_ARGMAX_RAW => ta_argmax_raw(ctx, out, a, window),
    PLAN_ARGMIN => ta_argmin(ctx, out, a, window),
    PLAN_ARGMIN_RAW => ta_argmin_raw(ctx, out, a, window),
    PLAN_CORR => ta_corr_nan(ctx, out, a, b, window, min_count),
    PLAN_COV => ta_cov_nan(ctx, out, a, b, window, min_count),
    _ => Err(Error::InvalidParameter(format!("unknown rolling plan op {code}"))),
  }
}

/// Run a compiled plan over `(groups, rows)` slot panels.
///
/// `slots` carries the input panels; the returned buffer starts as a copy of
/// them so the executor can write every intermediate in place. `plan` and
/// `params` are flat tables of four fields per op (see the module comment).
/// SAFETY: `pointer` must point to at least `slot_count * len` elements and the
/// returned slice must not outlive that allocation.
unsafe fn slot_slice<'a, NumT>(pointer: *const NumT, index: usize, len: usize) -> &'a [NumT] {
  unsafe { std::slice::from_raw_parts(pointer.add(index * len), len) }
}

/// 逐元素子图的融合执行：把整棵子图按 4K 元素分块求值，中间结果留在寄存器块里。
///
/// 程序格式（存放在 `table` 尾部 aux 区）：
///   * 前 `2 * input_count` 个浮点：每个输入 `[slot_id 或 -1, 立即数]`
///   * 之后每 4 个浮点一个节点：`[code, dst, src1, src2]`；`src < input_count`
///     表示输入，否则是中间寄存器（拓扑序，必然已算过）。
/// 每个块内按节点顺序跑紧循环，块之间复用寄存器缓冲，因此不会为每个节点分配
/// 整面板，也不会逐元素做 opcode 分派。
fn fused_operand<'a, NumT: Float>(
  register: usize,
  index: usize,
  input_count: usize,
  start: usize,
  stop: usize,
  inputs: &'a [PlanOperand<'a, NumT>],
  before: &'a [Vec<NumT>],
) -> Result<PlanOperand<'a, NumT>, Error> {
  if register < input_count {
    return Ok(match &inputs[register] {
      PlanOperand::Slot(values) => PlanOperand::Slot(&values[start..stop]),
      PlanOperand::Scalar(value) => PlanOperand::Scalar(*value),
    });
  }
  let local = register - input_count;
  if local >= index {
    return Err(Error::InvalidParameter(
      "fused register used before it is written".into(),
    ));
  }
  Ok(PlanOperand::Slot(&before[local]))
}

fn plan_fused<NumT: Float + Send + Sync>(
  out: &mut [NumT],
  pointer: *mut NumT,
  len: usize,
  program: &[NumT],
  input_count: usize,
  node_count: usize,
) -> Result<(), Error> {
  const BLOCK: usize = 4096;
  let needed = 2 * input_count + 4 * node_count;
  if program.len() < needed || node_count == 0 {
    return Err(Error::InvalidParameter("fused program is truncated".into()));
  }
  let mut inputs: Vec<PlanOperand<'_, NumT>> = Vec::with_capacity(input_count);
  for index in 0..input_count {
    let slot = program[2 * index].to_usize();
    let value = program[2 * index + 1];
    inputs.push(match slot {
      Some(slot) => PlanOperand::Slot(unsafe { slot_slice(pointer, slot, len) }),
      None => PlanOperand::Scalar(value),
    });
  }
  let nodes_base = 2 * input_count;
  let mut registers: Vec<Vec<NumT>> = (0..node_count)
    .map(|_| vec![NumT::zero(); BLOCK.min(out.len().max(1))])
    .collect();
  for start in (0..out.len()).step_by(BLOCK) {
    let stop = (start + BLOCK).min(out.len());
    let width = stop - start;
    for index in 0..node_count {
      let row = nodes_base + 4 * index;
      let code = program[row]
        .to_usize()
        .ok_or_else(|| Error::InvalidParameter("fused code is not an integer".into()))?;
      let src1 = program[row + 2]
        .to_usize()
        .ok_or_else(|| Error::InvalidParameter("fused register is not an integer".into()))?;
      let src2 = program[row + 3]
        .to_usize()
        .ok_or_else(|| Error::InvalidParameter("fused register is not an integer".into()))?;
      let (before, rest) = registers.split_at_mut(index);
      let target = &mut rest[0][..width];
      let a = fused_operand(src1, index, input_count, start, stop, &inputs, before)?;
      let b = fused_operand(src2, index, input_count, start, stop, &inputs, before)?;
      if (PLAN_NEG..=PLAN_NOT).contains(&code) {
        plan_unary(code, target, &a)?;
      } else if (PLAN_ADD..=PLAN_MIN).contains(&code)
        || (PLAN_GT..=PLAN_OR).contains(&code)
      {
        plan_binary(code, target, &a, &b)?;
      } else {
        return Err(Error::InvalidParameter(format!(
          "unsupported fused op {code}"
        )));
      }
    }
    out[start..stop].copy_from_slice(&registers[node_count - 1][..width]);
  }
  Ok(())
}

fn cross_op<NumT: Float + Send + Sync>(
  code: usize,
  ctx: &Context,
  out: &mut [NumT],
  a: &PlanOperand<'_, NumT>,
  b: Option<&[NumT]>,
  c: Option<&[NumT]>,
  d: Option<&[NumT]>,
  mask: Option<&[NumT]>,
  aux: &[NumT],
  operation: usize,
) -> Result<(), Error> {
  let signal = a.slot()?;
  match code {
    PLAN_RANK => ta_ft_rank(ctx, out, signal),
    PLAN_RANK_MASKED => ta_ft_rank_masked(
      ctx,
      out,
      signal,
      b.ok_or_else(|| Error::InvalidParameter("rank_masked needs a mask slot".into()))?,
    ),
    PLAN_ZSCORE => ta_ft_zscore(ctx, out, signal),
    PLAN_ORDINAL => ta_ft_ordinal_rank(
      ctx,
      out,
      signal,
      b.ok_or_else(|| Error::InvalidParameter("ordinal rank needs a mask slot".into()))?,
      aux,
      operation,
    ),
    PLAN_GROUP => ta_ft_group(
      ctx,
      out,
      signal,
      b.ok_or_else(|| Error::InvalidParameter("group op needs a mask slot".into()))?,
      aux,
      operation,
    ),
    PLAN_RESIDUALIZE_1 | PLAN_RESIDUALIZE_2 | PLAN_RESIDUALIZE_3 => {
      let count = code - PLAN_RESIDUALIZE_1 + 1;
      let e1 = b.ok_or_else(|| Error::InvalidParameter("residualize needs an exposure".into()))?;
      let e2 = if count >= 2 { c.unwrap_or(&[]) } else { &[] };
      let e3 = if count >= 3 { d.unwrap_or(&[]) } else { &[] };
      let mask = mask
        .ok_or_else(|| Error::InvalidParameter("residualize needs a mask slot".into()))?;
      ta_ft_residualize(ctx, out, signal, e1, e2, e3, mask, count)
    }
    _ => Err(Error::InvalidParameter(format!("unknown cross plan op {code}"))),
  }
}

/// Run a compiled plan over `(groups, rows)` slot panels.
///
/// `slots` carries the input panels; `aux` carries per-product/per-timestamp
/// vectors (ordinal tiebreak, group categories). The executor buffer starts as
/// a copy of the leaf slots so every intermediate can be written in place.
pub fn ta_ft_run_plan<NumT: Float + Send + Sync>(
  ctx: &Context,
  r: &mut [NumT],
  slots: &[NumT],
  table: &[NumT],
  slot_count: usize,
  op_count: usize,
  leaf_count: usize,
) -> Result<(), Error> {
  const PLAN_STRIDE: usize = 8;
  const PARAM_STRIDE: usize = 8;
  if slot_count == 0 || slots.is_empty() || slots.len() % slot_count != 0 {
    return Err(Error::LengthMismatch(slots.len(), slot_count));
  }
  if r.len() != slots.len() {
    return Err(Error::LengthMismatch(r.len(), slots.len()));
  }
  // The generator writes one table per plan: operator rows, parameter rows,
  // then the per-product aux vector.
  let table_len = op_count * PLAN_STRIDE + op_count * PARAM_STRIDE;
  if table.len() < table_len {
    return Err(Error::LengthMismatch(table.len(), table_len));
  }
  let (plan, rest) = table.split_at(op_count * PLAN_STRIDE);
  let (params, aux) = rest.split_at(op_count * PARAM_STRIDE);
  if leaf_count > slot_count {
    return Err(Error::InvalidParameter(format!(
      "leaf_count {leaf_count} exceeds slot_count {slot_count}"
    )));
  }
  let len = slots.len() / slot_count;
  let (groups, rows) = panel_layout(len, ctx.groups());
  // Leaves are allocated first by the compiler; every other slot is written
  // before it is read, so only the input panels need copying.
  r[..leaf_count * len].copy_from_slice(&slots[..leaf_count * len]);
  let pointer = r.as_mut_ptr();
  for index in 0..op_count {
    let base = index * PLAN_STRIDE;
    let param_base = index * PARAM_STRIDE;
    let code = plan[base]
      .to_usize()
      .ok_or_else(|| Error::InvalidParameter("plan code is not an integer".into()))?;
    let out_idx = plan[base + 1]
      .to_usize()
      .ok_or_else(|| Error::InvalidParameter("plan out slot is not an integer".into()))?;
    if out_idx >= slot_count {
      return Err(Error::InvalidParameter(format!(
        "plan out slot {out_idx} out of range (slots={slot_count})"
      )));
    }
    // 负的槽位号表示立即数或缺失操作数；值放在参数表第 5/6 列。
    let a_index = plan[base + 2].to_usize();
    let b_index = plan[base + 3].to_usize();
    let c_index = plan[base + 4].to_usize();
    let d_index = plan[base + 5].to_usize();
    let e_index = plan[base + 6].to_usize();
    for slot in [a_index, b_index, c_index, d_index, e_index].into_iter().flatten() {
      if slot >= slot_count {
        return Err(Error::InvalidParameter(format!(
          "plan input slot {slot} out of range (slots={slot_count})"
        )));
      }
      if slot == out_idx {
        return Err(Error::InvalidParameter(format!(
          "plan op {index} aliases output slot {out_idx} with an input"
        )));
      }
    }
    // SAFETY: every slot index is in range and disjoint from `out`; `r` lives
    // for the whole loop and the slices never outlive it.
    let out = unsafe { std::slice::from_raw_parts_mut(pointer.add(out_idx * len), len) };
    let a = match a_index {
      Some(slot) => PlanOperand::Slot(unsafe { slot_slice(pointer, slot, len) }),
      None => PlanOperand::Scalar(params[param_base + 4]),
    };
    let b = match b_index {
      Some(slot) => PlanOperand::Slot(unsafe { slot_slice(pointer, slot, len) }),
      None => PlanOperand::Scalar(params[param_base + 5]),
    };
    let c = c_index.map(|slot| unsafe { slot_slice(pointer, slot, len) });
    let d = d_index.map(|slot| unsafe { slot_slice(pointer, slot, len) });
    let mask = e_index.map(|slot| unsafe { slot_slice(pointer, slot, len) });
    let window = params[param_base].to_usize().unwrap_or(0);
    let min_count = params[param_base + 1].to_usize().unwrap_or(0);
    let quantile = params[param_base + 2];
    let periods = params[param_base + 3].to_i64().unwrap_or(0);
    let aux_offset = params[param_base + 6].to_usize().unwrap_or(0);
    let aux_len = params[param_base + 7].to_usize().unwrap_or(0);
    let aux_slice = if aux_len > 0 {
      aux.get(aux_offset..aux_offset + aux_len)
        .ok_or_else(|| Error::InvalidParameter("plan aux slice out of range".into()))?
    } else {
      &[]
    };
    if code == PLAN_FILL {
      out.fill(params[param_base + 4]);
    } else if code == PLAN_SHIFT {
      plan_shift(out, a.slot()?, groups, rows, periods)?;
    } else if (PLAN_NEG..=PLAN_NOT).contains(&code) {
      plan_unary(code, out, &a)?;
    } else if code == PLAN_WHERE {
      let when_true = c.ok_or_else(|| {
        Error::InvalidParameter("where needs a third operand slot".into())
      })?;
      plan_where(out, &a, &b, &PlanOperand::Slot(when_true));
    } else if (PLAN_ADD..=PLAN_MIN).contains(&code)
      || (PLAN_GT..=PLAN_OR).contains(&code)
    {
      plan_binary(code, out, &a, &b)?;
    } else if code == PLAN_SCOPE {
      ta_ft_scope_agg(ctx, out, a.slot()?, aux_slice, min_count, window, quantile)?;
    } else if code == PLAN_FUSED {
      plan_fused(
        out,
        pointer,
        len,
        aux_slice,
        params[param_base + 4].to_usize().unwrap_or(0),
        params[param_base + 5].to_usize().unwrap_or(0),
      )?;
    } else if (PLAN_RANK..=PLAN_RESIDUALIZE_3).contains(&code) {
      cross_op(code, ctx, out, &a, b.slots_ref(), c, d, mask, aux_slice, window)?;
    } else {
      rolling_op(code, ctx, out, a.slot()?, b.slot()?, window, min_count, quantile)?;
    }
  }
  Ok(())
}

#[cfg(test)]
mod tests {
  use super::*;

  #[test]
  fn plan_shift_add_and_sign() {
    // 2 products x 4 bars; slot 0 input, slot 1 constant 1.0,
    // op0: shift(input, 1) -> slot 2, op1: add(slot2, const) -> slot 3,
    // op2: sign(slot3) -> slot 4.
    let groups = 2usize;
    let rows = 4usize;
    let input = [1.0, 2.0, 3.0, 4.0, 10.0, 20.0, 30.0, 40.0];
    let mut slots = vec![0.0; groups * rows * 5];
    slots[..groups * rows].copy_from_slice(&input);
    for value in slots.iter_mut().skip(groups * rows).take(groups * rows) {
      *value = 1.0;
    }
    let plan = [
      PLAN_SHIFT as f64, 2.0, 0.0, 0.0, -1.0, -1.0, -1.0, -1.0,
      PLAN_ADD as f64, 3.0, 2.0, -1.0, -1.0, -1.0, -1.0, -1.0,
      PLAN_SIGN as f64, 4.0, 3.0, 3.0, -1.0, -1.0, -1.0, -1.0,
    ];
    let params = [
      0.0, 0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0, // shift(input, 1)
      0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, // add, b = 1.0 immediate
      0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, // sign
    ];
    let mut table = Vec::new();
    table.extend_from_slice(&plan);
    table.extend_from_slice(&params);
    let ctx = Context::new(0, groups as u32, 0);
    let mut out = vec![0.0; slots.len()];
    ta_ft_run_plan(&ctx, &mut out, &slots, &table, 5, 3, 2).unwrap();
    let shifted = &out[2 * groups * rows..3 * groups * rows];
    let signed = &out[4 * groups * rows..5 * groups * rows];
    assert!(shifted[0].is_nan() && shifted[4].is_nan());
    assert_eq!(shifted[1], 1.0);
    assert_eq!(shifted[5], 10.0);
    assert!(signed[0].is_nan());
    assert_eq!(signed[1], 1.0);
    assert_eq!(signed[2], 1.0);
    assert_eq!(signed[3], 1.0);
  }

  #[test]
  fn plan_rolling_mean_matches_window() {
    let groups = 1usize;
    let rows = 5usize;
    let input = [1.0, 2.0, 3.0, 4.0, 5.0];
    let mut slots = vec![0.0; rows * 2];
    slots[..rows].copy_from_slice(&input);
    let plan = [PLAN_MEAN as f64, 1.0, 0.0, 0.0, -1.0, -1.0, -1.0, -1.0];
    let params = [2.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0];
    let mut table = Vec::new();
    table.extend_from_slice(&plan);
    table.extend_from_slice(&params);
    let ctx = Context::new(0, groups as u32, 0);
    let mut out = vec![0.0; slots.len()];
    ta_ft_run_plan(&ctx, &mut out, &slots, &table, 2, 1, 1).unwrap();
    let mean = &out[rows..2 * rows];
    // min_count = 1, so the first partial window is already eligible.
    assert_eq!(mean[0], 1.0);
    assert_eq!(mean[1], 1.5);
    assert_eq!(mean[2], 2.5);
  }
}
