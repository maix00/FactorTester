pub fn register_ta_funcs(lua: &Lua) -> LuaResult<()> {
    lua.globals().set(
      "ABS",
      lua.create_function(|lua, (input,): (NumArray,)| {
        let mut r = vec![0.0; input.len()];
        ta_abs::<f64>(&ctx(lua), &mut r, &input)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "ALL",
      lua.create_function(|lua, (condition, periods): (BoolArray, usize)| {
        let mut r = vec![false; condition.len()];
        ta_all(&ctx(lua), &mut r, &condition, periods)?;
        Ok(BoolArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "ALPHA",
      lua.create_function(|lua, (input, benchmark, periods): (NumArray, NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_alpha::<f64>(&ctx(lua), &mut r, &input, &benchmark, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "ANY",
      lua.create_function(|lua, (condition, periods): (BoolArray, usize)| {
        let mut r = vec![false; condition.len()];
        ta_any(&ctx(lua), &mut r, &condition, periods)?;
        Ok(BoolArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "ARGMAX",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_argmax::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "ARGMAX_RAW",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_argmax_raw::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "ARGMIN",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_argmin::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "ARGMIN_RAW",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_argmin_raw::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "BACKFILL",
      lua.create_function(|lua, (input,): (NumArray,)| {
        let mut r = vec![0.0; input.len()];
        ta_backfill::<f64>(&ctx(lua), &mut r, &input)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "BACKSET",
      lua.create_function(|lua, (condition, periods): (BoolArray, usize)| {
        let mut r = vec![false; condition.len()];
        ta_backset(&ctx(lua), &mut r, &condition, periods)?;
        Ok(BoolArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "BARSLAST",
      lua.create_function(|lua, (input,): (BoolArray,)| {
        let mut r = vec![0.0; input.len()];
        ta_barslast::<f64>(&ctx(lua), &mut r, &input)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "BARSSINCE",
      lua.create_function(|lua, (input,): (BoolArray,)| {
        let mut r = vec![0.0; input.len()];
        ta_barssince::<f64>(&ctx(lua), &mut r, &input)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "BETA",
      lua.create_function(|lua, (input, benchmark, periods): (NumArray, NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_beta::<f64>(&ctx(lua), &mut r, &input, &benchmark, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "BINS",
      lua.create_function(|lua, (input, bins): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_bins::<f64>(&ctx(lua), &mut r, &input, bins)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "BW_SPLIT",
      lua.create_function(|lua, (price, dividend, transfer_shares, right_shares, right_price): (NumArray, NumArray, NumArray, NumArray, NumArray)| {
        let mut r = vec![0.0; price.len()];
        ta_bw_split::<f64>(&ctx(lua), &mut r, &price, &dividend, &transfer_shares, &right_shares, &right_price)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "BW_SPLIT_FACTOR",
      lua.create_function(|lua, (price, dividend, transfer_shares, right_shares, right_price): (NumArray, NumArray, NumArray, NumArray, NumArray)| {
        let mut r = vec![0.0; price.len()];
        ta_bw_split_factor::<f64>(&ctx(lua), &mut r, &price, &dividend, &transfer_shares, &right_shares, &right_price)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "CC_RANK",
      lua.create_function(|lua, (input,): (NumArray,)| {
        let mut r = vec![0.0; input.len()];
        ta_cc_rank::<f64>(&ctx(lua), &mut r, &input)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "CC_ZSCORE",
      lua.create_function(|lua, (input,): (NumArray,)| {
        let mut r = vec![0.0; input.len()];
        ta_cc_zscore::<f64>(&ctx(lua), &mut r, &input)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "CORR",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_corr::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "CORR2",
      lua.create_function(|lua, (x, y, periods): (NumArray, NumArray, usize)| {
        let mut r = vec![0.0; x.len()];
        ta_corr2::<f64>(&ctx(lua), &mut r, &x, &y, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "CORR_NAN",
      lua.create_function(|lua, (left, right, periods, min_count): (NumArray, NumArray, usize, usize)| {
        let mut r = vec![0.0; left.len()];
        ta_corr_nan::<f64>(&ctx(lua), &mut r, &left, &right, periods, min_count)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "COUNT",
      lua.create_function(|lua, (input, periods): (BoolArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_count::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "COUNT_NANS",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_count_nans::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "COUNT_V",
      lua.create_function(|lua, (input, periods): (BoolArray, NumArray)| {
        let mut r = vec![0.0; input.len()];
        let periods_usize: Vec<usize> = periods.iter().map(|&x| x as usize).collect();
        ta_count_v::<f64>(&ctx(lua), &mut r, &input, &periods_usize)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "COV",
      lua.create_function(|lua, (x, y, periods): (NumArray, NumArray, usize)| {
        let mut r = vec![0.0; x.len()];
        ta_cov::<f64>(&ctx(lua), &mut r, &x, &y, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "COV_NAN",
      lua.create_function(|lua, (left, right, periods, min_count): (NumArray, NumArray, usize, usize)| {
        let mut r = vec![0.0; left.len()];
        ta_cov_nan::<f64>(&ctx(lua), &mut r, &left, &right, periods, min_count)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "CROSS",
      lua.create_function(|lua, (a, b): (NumArray, NumArray)| {
        let mut r = vec![false; a.len()];
        ta_cross::<f64>(&ctx(lua), &mut r, &a, &b)?;
        Ok(BoolArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "DMA",
      lua.create_function(|lua, (input, weight): (NumArray, f64)| {
        let mut r = vec![0.0; input.len()];
        ta_dma::<f64>(&ctx(lua), &mut r, &input, weight)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "DMA_V",
      lua.create_function(|lua, (input, weight): (NumArray, NumArray)| {
        let mut r = vec![0.0; input.len()];
        ta_dma_v::<f64>(&ctx(lua), &mut r, &input, &weight)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "EMA",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_ema::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "EMA_ADJUST",
      lua.create_function(|lua, (input, periods, min_count): (NumArray, usize, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_ema_adjust::<f64>(&ctx(lua), &mut r, &input, periods, min_count)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "EMA_V",
      lua.create_function(|lua, (input, periods): (NumArray, NumArray)| {
        let mut r = vec![0.0; input.len()];
        let periods_usize: Vec<usize> = periods.iter().map(|&x| x as usize).collect();
        ta_ema_v::<f64>(&ctx(lua), &mut r, &input, &periods_usize)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "ENTROPY",
      lua.create_function(|lua, (input, periods, bins): (NumArray, usize, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_entropy::<f64>(&ctx(lua), &mut r, &input, periods, bins)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FILTER",
      lua.create_function(|lua, (condition, periods): (BoolArray, usize)| {
        let mut r = vec![false; condition.len()];
        ta_filter(&ctx(lua), &mut r, &condition, periods)?;
        Ok(BoolArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FRET",
      lua.create_function(|lua, (open, close, is_calc, delay, periods): (NumArray, NumArray, NumArray, usize, usize)| {
        let mut r = vec![0.0; open.len()];
        ta_fret::<f64>(&ctx(lua), &mut r, &open, &close, &is_calc, delay, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_AVERAGE_COST_CHAIN",
      lua.create_function(|lua, (fill_qty, price, multiplier, prior_qty, prior_cost, mode): (NumArray, NumArray, NumArray, f64, f64, usize)| {
        let mut r = vec![0.0; fill_qty.len()];
        ta_ft_average_cost_chain::<f64>(&ctx(lua), &mut r, &fill_qty, &price, &multiplier, prior_qty, prior_cost, mode)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_BAR_VISIBILITY",
      lua.create_function(|lua, (indices, open_basis, open_delay, end_delay, freq): (NumArray, usize, f64, f64, f64)| {
        let mut r = vec![0.0; indices.len()];
        ta_ft_bar_visibility::<f64>(&ctx(lua), &mut r, &indices, open_basis, open_delay, end_delay, freq)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_CORR",
      lua.create_function(|lua, (left, right): (NumArray, NumArray)| {
        let mut r = vec![0.0; left.len()];
        ta_ft_corr::<f64>(&ctx(lua), &mut r, &left, &right)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_COV",
      lua.create_function(|lua, (left, right): (NumArray, NumArray)| {
        let mut r = vec![0.0; left.len()];
        ta_ft_cov::<f64>(&ctx(lua), &mut r, &left, &right)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_CURVE_FIT",
      lua.create_function(|lua, (values, days, lengths, depth, op): (NumArray, NumArray, NumArray, usize, usize)| {
        let mut r = vec![0.0; values.len()];
        ta_ft_curve_fit::<f64>(&ctx(lua), &mut r, &values, &days, &lengths, depth, op)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_CURVE_PAIR",
      lua.create_function(|lua, (values, days, lengths, near, far, op): (NumArray, NumArray, NumArray, usize, usize, usize)| {
        let mut r = vec![0.0; values.len()];
        ta_ft_curve_pair::<f64>(&ctx(lua), &mut r, &values, &days, &lengths, near, far, op)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_DYNAMIC_ARG",
      lua.create_function(|lua, (input, starts, ends, period, flags): (NumArray, NumArray, NumArray, usize, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_ft_dynamic_arg::<f64>(&ctx(lua), &mut r, &input, &starts, &ends, period, flags)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_DYNAMIC_MASK",
      lua.create_function(|lua, (input, starts, ends, period): (NumArray, NumArray, NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_ft_dynamic_mask::<f64>(&ctx(lua), &mut r, &input, &starts, &ends, period)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_EVENT_ORDER",
      lua.create_function(|lua, (timestamps, kinds, sequences): (NumArray, NumArray, NumArray)| {
        let mut r = vec![0.0; timestamps.len()];
        ta_ft_event_order::<f64>(&ctx(lua), &mut r, &timestamps, &kinds, &sequences)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_EXEC_POSITIONS",
      lua.create_function(|lua, (indices, offsets, query, _delay): (NumArray, NumArray, f64, usize)| {
        let mut r = vec![0.0; indices.len()];
        ta_ft_exec_positions::<f64>(&ctx(lua), &mut r, &indices, &offsets, query, _delay)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_EXEC_SCHEDULE_TS",
      lua.create_function(|lua, (indices, offsets, delay, freq, open_delay, end_delay, open_basis, mode): (NumArray, NumArray, usize, f64, f64, f64, usize, usize)| {
        let mut r = vec![0.0; indices.len()];
        ta_ft_exec_schedule_ts::<f64>(&ctx(lua), &mut r, &indices, &offsets, delay, freq, open_delay, end_delay, open_basis, mode)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_GROUP",
      lua.create_function(|lua, (input, mask, category, op): (NumArray, NumArray, NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_ft_group::<f64>(&ctx(lua), &mut r, &input, &mask, &category, op)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_GROUP_REDUCE",
      lua.create_function(|lua, (input, category, weight, op): (NumArray, NumArray, NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_ft_group_reduce::<f64>(&ctx(lua), &mut r, &input, &category, &weight, op)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_ORDINAL_RANK",
      lua.create_function(|lua, (input, mask, tiebreak, ascending): (NumArray, NumArray, NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_ft_ordinal_rank::<f64>(&ctx(lua), &mut r, &input, &mask, &tiebreak, ascending)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_RANK",
      lua.create_function(|lua, (input,): (NumArray,)| {
        let mut r = vec![0.0; input.len()];
        ta_ft_rank::<f64>(&ctx(lua), &mut r, &input)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_RANK_MASKED",
      lua.create_function(|lua, (input, mask): (NumArray, NumArray)| {
        let mut r = vec![0.0; input.len()];
        ta_ft_rank_masked::<f64>(&ctx(lua), &mut r, &input, &mask)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_RESIDUALIZE",
      lua.create_function(|lua, (signal, exposure1, exposure2, exposure3, mask, exposure_count): (NumArray, NumArray, NumArray, NumArray, NumArray, usize)| {
        let mut r = vec![0.0; signal.len()];
        ta_ft_residualize::<f64>(&ctx(lua), &mut r, &signal, &exposure1, &exposure2, &exposure3, &mask, exposure_count)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_RUN_PLAN",
      lua.create_function(|lua, (slots, table, slot_count, op_count, leaf_count): (NumArray, NumArray, usize, usize, usize)| {
        let mut r = vec![0.0; slots.len()];
        ta_ft_run_plan::<f64>(&ctx(lua), &mut r, &slots, &table, slot_count, op_count, leaf_count)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_SCOPE_AGG",
      lua.create_function(|lua, (input, keys, min_count, op, quantile): (NumArray, NumArray, usize, usize, f64)| {
        let mut r = vec![0.0; input.len()];
        ta_ft_scope_agg::<f64>(&ctx(lua), &mut r, &input, &keys, min_count, op, quantile)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_SCOPE_TRUNC",
      lua.create_function(|lua, (input, keys, trunc_start, trunc_end, min_count, op, quantile): (NumArray, NumArray, usize, usize, usize, usize, f64)| {
        let mut r = vec![0.0; input.len()];
        ta_ft_scope_trunc::<f64>(&ctx(lua), &mut r, &input, &keys, trunc_start, trunc_end, min_count, op, quantile)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_SPEARMAN",
      lua.create_function(|lua, (left, right): (NumArray, NumArray)| {
        let mut r = vec![0.0; left.len()];
        ta_ft_spearman::<f64>(&ctx(lua), &mut r, &left, &right)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_TARGET_QUANTITIES",
      lua.create_function(|lua, (prices, multipliers, weights, current, lot_sizes, equity, round_policy, mode): (NumArray, NumArray, NumArray, NumArray, NumArray, f64, usize, usize)| {
        let mut r = vec![0.0; prices.len()];
        ta_ft_target_quantities::<f64>(&ctx(lua), &mut r, &prices, &multipliers, &weights, &current, &lot_sizes, equity, round_policy, mode)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FT_ZSCORE",
      lua.create_function(|lua, (input,): (NumArray,)| {
        let mut r = vec![0.0; input.len()];
        ta_ft_zscore::<f64>(&ctx(lua), &mut r, &input)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FW_SPLIT",
      lua.create_function(|lua, (price, dividend, transfer_shares, right_shares, right_price): (NumArray, NumArray, NumArray, NumArray, NumArray)| {
        let mut r = vec![0.0; price.len()];
        ta_fw_split::<f64>(&ctx(lua), &mut r, &price, &dividend, &transfer_shares, &right_shares, &right_price)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "FW_SPLIT_FACTOR",
      lua.create_function(|lua, (price, dividend, transfer_shares, right_shares, right_price): (NumArray, NumArray, NumArray, NumArray, NumArray)| {
        let mut r = vec![0.0; price.len()];
        ta_fw_split_factor::<f64>(&ctx(lua), &mut r, &price, &dividend, &transfer_shares, &right_shares, &right_price)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "GROUP_RANK",
      lua.create_function(|lua, (category, input): (NumArray, NumArray)| {
        let mut r = vec![0.0; category.len()];
        ta_group_rank::<f64>(&ctx(lua), &mut r, &category, &input)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "GROUP_ZSCORE",
      lua.create_function(|lua, (category, input): (NumArray, NumArray)| {
        let mut r = vec![0.0; category.len()];
        ta_group_zscore::<f64>(&ctx(lua), &mut r, &category, &input)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "HHV",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_hhv::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "HHV_V",
      lua.create_function(|lua, (input, periods): (NumArray, NumArray)| {
        let mut r = vec![0.0; input.len()];
        let periods_usize: Vec<usize> = periods.iter().map(|&x| x as usize).collect();
        ta_hhv_v::<f64>(&ctx(lua), &mut r, &input, &periods_usize)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "HHVBARS",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_hhvbars::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "HHVBARS_V",
      lua.create_function(|lua, (input, periods): (NumArray, NumArray)| {
        let mut r = vec![0.0; input.len()];
        let periods_usize: Vec<usize> = periods.iter().map(|&x| x as usize).collect();
        ta_hhvbars_v::<f64>(&ctx(lua), &mut r, &input, &periods_usize)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "INTERCEPT",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_intercept::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "KURTOSIS",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_kurtosis::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "LAST",
      lua.create_function(|lua, (condition,): (BoolArray,)| {
        let mut r = vec![0.0; condition.len()];
        ta_last::<f64>(&ctx(lua), &mut r, &condition)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "LINREG_R2",
      lua.create_function(|lua, (input, periods, min_count): (NumArray, usize, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_linreg_r2::<f64>(&ctx(lua), &mut r, &input, periods, min_count)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "LINREG_RESID_STD",
      lua.create_function(|lua, (input, periods, min_count): (NumArray, usize, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_linreg_resid_std::<f64>(&ctx(lua), &mut r, &input, periods, min_count)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "LINREG_SLOPE",
      lua.create_function(|lua, (input, periods, min_count): (NumArray, usize, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_linreg_slope::<f64>(&ctx(lua), &mut r, &input, periods, min_count)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "LINREG_TSTAT",
      lua.create_function(|lua, (input, periods, min_count): (NumArray, usize, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_linreg_tstat::<f64>(&ctx(lua), &mut r, &input, periods, min_count)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "LLV",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_llv::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "LLV_V",
      lua.create_function(|lua, (input, periods): (NumArray, NumArray)| {
        let mut r = vec![0.0; input.len()];
        let periods_usize: Vec<usize> = periods.iter().map(|&x| x as usize).collect();
        ta_llv_v::<f64>(&ctx(lua), &mut r, &input, &periods_usize)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "LLVBARS",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_llvbars::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "LLVBARS_V",
      lua.create_function(|lua, (input, periods): (NumArray, NumArray)| {
        let mut r = vec![0.0; input.len()];
        let periods_usize: Vec<usize> = periods.iter().map(|&x| x as usize).collect();
        ta_llvbars_v::<f64>(&ctx(lua), &mut r, &input, &periods_usize)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "LONGCROSS",
      lua.create_function(|lua, (a, b, n): (NumArray, NumArray, usize)| {
        let mut r = vec![false; a.len()];
        ta_longcross::<f64>(&ctx(lua), &mut r, &a, &b, n)?;
        Ok(BoolArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "LWMA",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_lwma::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "LWMA_V",
      lua.create_function(|lua, (input, periods): (NumArray, NumArray)| {
        let mut r = vec![0.0; input.len()];
        let periods_usize: Vec<usize> = periods.iter().map(|&x| x as usize).collect();
        ta_lwma_v::<f64>(&ctx(lua), &mut r, &input, &periods_usize)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "MA",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_ma::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "MA_V",
      lua.create_function(|lua, (input, periods): (NumArray, NumArray)| {
        let mut r = vec![0.0; input.len()];
        let periods_usize: Vec<usize> = periods.iter().map(|&x| x as usize).collect();
        ta_ma_v::<f64>(&ctx(lua), &mut r, &input, &periods_usize)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "MAD",
      lua.create_function(|lua, (input, periods, min_count): (NumArray, usize, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_mad::<f64>(&ctx(lua), &mut r, &input, periods, min_count)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "MAX",
      lua.create_function(|lua, (a, b): (NumArray, NumArray)| {
        let mut r = vec![0.0; a.len()];
        ta_max::<f64>(&ctx(lua), &mut r, &a, &b)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "MAX_DRAWDOWN",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_max_drawdown::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "MAX_NAN",
      lua.create_function(|lua, (input, periods, min_count): (NumArray, usize, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_max_nan::<f64>(&ctx(lua), &mut r, &input, periods, min_count)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "MEAN_NAN",
      lua.create_function(|lua, (input, periods, min_count): (NumArray, usize, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_mean_nan::<f64>(&ctx(lua), &mut r, &input, periods, min_count)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "MEDIAN",
      lua.create_function(|lua, (input, periods, min_count): (NumArray, usize, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_median::<f64>(&ctx(lua), &mut r, &input, periods, min_count)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "MIN",
      lua.create_function(|lua, (a, b): (NumArray, NumArray)| {
        let mut r = vec![0.0; a.len()];
        ta_min::<f64>(&ctx(lua), &mut r, &a, &b)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "MIN_MAX_DIFF",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_min_max_diff::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "MIN_NAN",
      lua.create_function(|lua, (input, periods, min_count): (NumArray, usize, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_min_nan::<f64>(&ctx(lua), &mut r, &input, periods, min_count)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "MOMENT",
      lua.create_function(|lua, (input, periods, k): (NumArray, usize, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_moment::<f64>(&ctx(lua), &mut r, &input, periods, k)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "NEUTRALIZE",
      lua.create_function(|lua, (category, input): (NumArray, NumArray)| {
        let mut r = vec![0.0; category.len()];
        ta_neutralize::<f64>(&ctx(lua), &mut r, &category, &input)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "PRODUCT",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_product::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "QUANTILE",
      lua.create_function(|lua, (input, periods, q): (NumArray, usize, f64)| {
        let mut r = vec![0.0; input.len()];
        ta_quantile::<f64>(&ctx(lua), &mut r, &input, periods, q)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "QUANTILE_NAN",
      lua.create_function(|lua, (input, periods, min_count, q): (NumArray, usize, usize, f64)| {
        let mut r = vec![0.0; input.len()];
        ta_quantile_nan::<f64>(&ctx(lua), &mut r, &input, periods, min_count, q)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "RANK",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_rank::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "RCROSS",
      lua.create_function(|lua, (a, b): (NumArray, NumArray)| {
        let mut r = vec![false; a.len()];
        ta_rcross::<f64>(&ctx(lua), &mut r, &a, &b)?;
        Ok(BoolArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "REF",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_ref::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "REF_V",
      lua.create_function(|lua, (input, periods): (NumArray, NumArray)| {
        let mut r = vec![0.0; input.len()];
        let periods_usize: Vec<usize> = periods.iter().map(|&x| x as usize).collect();
        ta_ref_v::<f64>(&ctx(lua), &mut r, &input, &periods_usize)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "REGBETA",
      lua.create_function(|lua, (y, x, periods): (NumArray, NumArray, usize)| {
        let mut r = vec![0.0; y.len()];
        ta_regbeta::<f64>(&ctx(lua), &mut r, &y, &x, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "REGRESI",
      lua.create_function(|lua, (y, x, periods): (NumArray, NumArray, usize)| {
        let mut r = vec![0.0; y.len()];
        ta_regresi::<f64>(&ctx(lua), &mut r, &y, &x, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "RLONGCROSS",
      lua.create_function(|lua, (a, b, n): (NumArray, NumArray, usize)| {
        let mut r = vec![false; a.len()];
        ta_rlongcross::<f64>(&ctx(lua), &mut r, &a, &b, n)?;
        Ok(BoolArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "SCAN_ADD",
      lua.create_function(|lua, (input, condition): (NumArray, BoolArray)| {
        let mut r = vec![0.0; input.len()];
        ta_scan_add::<f64>(&ctx(lua), &mut r, &input, &condition)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "SCAN_MUL",
      lua.create_function(|lua, (input, condition): (NumArray, BoolArray)| {
        let mut r = vec![0.0; input.len()];
        ta_scan_mul::<f64>(&ctx(lua), &mut r, &input, &condition)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "SHARPE",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_sharpe::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "SKEW_EXACT",
      lua.create_function(|lua, (input, periods, min_count): (NumArray, usize, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_skew_exact::<f64>(&ctx(lua), &mut r, &input, periods, min_count)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "SKEWNESS",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_skewness::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "SLOPE",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_slope::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "SMA",
      lua.create_function(|lua, (input, n, m): (NumArray, usize, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_sma::<f64>(&ctx(lua), &mut r, &input, n, m)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "SMA_V",
      lua.create_function(|lua, (input, ns, m): (NumArray, NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        let ns_usize: Vec<usize> = ns.iter().map(|&x| x as usize).collect();
        ta_sma_v::<f64>(&ctx(lua), &mut r, &input, &ns_usize, m)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "STD_NAN",
      lua.create_function(|lua, (input, periods, min_count): (NumArray, usize, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_std_nan::<f64>(&ctx(lua), &mut r, &input, periods, min_count)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "STDDEV",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_stddev::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "SUM",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_sum::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "SUM_NAN",
      lua.create_function(|lua, (input, periods, min_count): (NumArray, usize, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_sum_nan::<f64>(&ctx(lua), &mut r, &input, periods, min_count)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "SUMBARS",
      lua.create_function(|lua, (input, amount): (NumArray, f64)| {
        let mut r = vec![0.0; input.len()];
        ta_sumbars::<f64>(&ctx(lua), &mut r, &input, amount)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "SUMIF",
      lua.create_function(|lua, (input, condition, periods): (NumArray, BoolArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_sumif::<f64>(&ctx(lua), &mut r, &input, &condition, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "VAR",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_var::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "VAR_NAN",
      lua.create_function(|lua, (input, periods, min_count): (NumArray, usize, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_var_nan::<f64>(&ctx(lua), &mut r, &input, periods, min_count)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "WEIGHTED_DELAY",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_weighted_delay::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "WHERE",
      lua.create_function(|lua, (condition, a, b): (BoolArray, NumArray, NumArray)| {
        let mut r = vec![0.0; condition.len()];
        ta_where::<f64>(&ctx(lua), &mut r, &condition, &a, &b)?;
        Ok(NumArray::from(r))
      })?,
    )?;
    lua.globals().set(
      "ZSCORE",
      lua.create_function(|lua, (input, periods): (NumArray, usize)| {
        let mut r = vec![0.0; input.len()];
        ta_zscore::<f64>(&ctx(lua), &mut r, &input, periods)?;
        Ok(NumArray::from(r))
      })?,
    )?;
  Ok(())
}
