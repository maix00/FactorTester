#!/usr/bin/env python3
"""
Compute Alpha 101 using the pandas (DolphinDB) implementation,
then compare with py-alpha-lib and polars_ta results.

Both compute on the same dataPerformance.csv data.
"""

import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore", category=RuntimeWarning)

# ── Paths ───────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = PROJECT_ROOT / "dataPerformance.csv"
AL_CSV = PROJECT_ROOT / "al_alpha101.csv"
PT_CSV = PROJECT_ROOT / "pt_alpha101.csv"
PD_OUTPUT = PROJECT_ROOT / "pd_alpha101.csv"
PD_TIMING = PROJECT_ROOT / "pd_timing.csv"
COMPARISON_OUTPUT = PROJECT_ROOT / "comparison_all.csv"

UNSUPPORTED = {48, 56, 58, 59, 63, 67, 69, 70, 76, 79, 80, 82, 87, 89, 90, 91, 93, 97, 100}


# ── Step 1: Compute Alpha 101 with pandas ───────────────────────────────────
def step1_compute_pandas():
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "examples" / "wq101"))
    from pd_.alpha101_adjusted import Alphas

    print("=" * 70)
    print("Step 1: Computing Alpha 101 with pandas (DolphinDB impl)")
    print("=" * 70)

    # Load and pivot data
    t0 = time.time()
    data = pd.read_csv(DATA_PATH)
    df = data.pivot(index="tradetime", columns="securityid")
    securities = df["close"].columns.tolist()  # security IDs in pivot order
    tradetimes = df.index.tolist()
    ctx = Alphas(df)
    load_time_ms = (time.time() - t0) * 1000

    security_count = len(securities)
    trade_count = len(tradetimes)
    print(f"Data loaded in {load_time_ms:.0f}ms ({security_count} securities x {trade_count} dates)")

    # Build (securityid, date) index for output
    dates = [
        pd.to_datetime(t[:10].replace(".", "-")) for t in tradetimes
    ]
    # Columns: securityid, date, then alpha values
    # Build as dict of arrays for efficiency
    rows = []
    for i, t in enumerate(tradetimes):
        for j, sec in enumerate(securities):
            rows.append((sec, dates[i]))
    pd_out = pd.DataFrame(rows, columns=["securityid", "date"])

    timing = [("data_load", load_time_ms, "ok")]
    alpha_results = {}  # col_name -> flat numpy array

    for no in range(1, 102):
        col = f"alpha_{no:03d}"
        if no in UNSUPPORTED:
            timing.append((col, None, "unsupported"))
            continue

        fn_name = f"alpha{no:03d}"
        fn = getattr(Alphas, fn_name, None)
        if fn is None:
            timing.append((col, None, "not_implemented"))
            print(f"  Alpha #{no:03d}: NOT IMPLEMENTED")
            continue

        try:
            t1 = time.time()
            result = fn(ctx)
            elapsed_ms = (time.time() - t1) * 1000

            # Convert pivoted result (tradetime × securityid) to flat array
            if isinstance(result, pd.DataFrame):
                # Ensure columns match securities order
                if result.shape == (trade_count, security_count):
                    result.columns = securities
                elif result.shape[0] == trade_count:
                    # May have different column count, try to align
                    result = result.reindex(columns=securities)
                vals = result.values.flatten(order="C")  # row-major: all secs for date1, then date2, ...
            elif isinstance(result, pd.Series):
                if len(result) == trade_count * security_count:
                    vals = result.values
                elif len(result) == trade_count:
                    # Single-column result, broadcast
                    vals = np.repeat(result.values, security_count)
                else:
                    vals = np.full(trade_count * security_count, np.nan)
            else:
                vals = np.full(trade_count * security_count, np.nan)

            alpha_results[col] = vals
            timing.append((col, elapsed_ms, "ok"))
            print(f"  Alpha #{no:03d}: {elapsed_ms:8.1f}ms")
        except Exception as e:
            err_msg = str(e).split("\n")[0][:80]
            timing.append((col, None, f"error: {err_msg}"))
            print(f"  Alpha #{no:03d}: ERROR - {err_msg}")

    # Attach all alpha columns at once
    for col, vals in alpha_results.items():
        pd_out[col] = vals

    pd_out.to_csv(PD_OUTPUT, index=False)
    print(f"\nSaved to {PD_OUTPUT} ({pd_out.shape})")

    timing_df = pd.DataFrame(timing, columns=["alpha", "time_ms", "status"])
    timing_df.to_csv(PD_TIMING, index=False)
    print(f"Timing saved to {PD_TIMING}")

    return pd_out, timing_df


# ── Step 2: Compare all implementations ─────────────────────────────────────
def _compare_pair(merged, col, suffix_a, suffix_b, all_dates):
    """Compare two implementations for a single alpha."""
    a_col, b_col = f"{col}_{suffix_a}", f"{col}_{suffix_b}"

    if a_col not in merged.columns or b_col not in merged.columns:
        has_a = a_col in merged.columns
        has_b = b_col in merged.columns
        return {"status": f"missing: {suffix_a}={'Y' if has_a else 'N'} {suffix_b}={'Y' if has_b else 'N'}"}

    a_vals = merged[a_col].values.astype(np.float64)
    b_vals = merged[b_col].values.astype(np.float64)

    mask = np.isfinite(a_vals) & np.isfinite(b_vals)
    a_clean = a_vals[mask]
    b_clean = b_vals[mask]
    n = len(a_clean)

    if n < 30:
        return {"status": f"insufficient (n={n})", "n_valid": n}

    pearson_r, _ = stats.pearsonr(a_clean, b_clean)
    spearman_r, _ = stats.spearmanr(a_clean, b_clean)
    mae = np.mean(np.abs(a_clean - b_clean))

    # Cross-sectional IC
    ic_list = []
    for dt in all_dates:
        dt_mask = (merged["date"] == dt).values & mask
        if dt_mask.sum() < 10:
            continue
        a = a_vals[dt_mask]
        b = b_vals[dt_mask]
        r, _ = stats.spearmanr(a, b)
        if np.isfinite(r):
            ic_list.append(r)

    ic_mean = np.mean(ic_list) if ic_list else np.nan

    return {
        "status": "ok",
        "n_valid": n,
        "pearson_r": round(pearson_r, 6),
        "spearman_r": round(spearman_r, 6),
        "mae": round(mae, 6),
        "ic_mean": round(ic_mean, 6) if np.isfinite(ic_mean) else np.nan,
    }


def step2_compare(pd_df):
    print("\n" + "=" * 70)
    print("Step 2: Three-way comparison (pandas vs alpha-lib vs polars_ta)")
    print("=" * 70)

    # Load all available results
    dfs = {"pd": pd_df}
    for name, path in [("al", AL_CSV), ("pt", PT_CSV)]:
        if path.exists():
            df = pd.read_csv(path)
            df["date"] = pd.to_datetime(df["date"])
            dfs[name] = df
            print(f"  Loaded {name}: {df.shape}")
        else:
            print(f"  {name}: {path.name} NOT FOUND")

    pd_df["date"] = pd.to_datetime(pd_df["date"])

    # Merge all available pairs
    pairs = []
    if "al" in dfs:
        pairs.append(("pd", "al"))
    if "pt" in dfs:
        pairs.append(("pd", "pt"))
    if "al" in dfs and "pt" in dfs:
        pairs.append(("al", "pt"))

    results = []
    alpha_cols = [f"alpha_{i:03d}" for i in range(1, 102)]

    for sa, sb in pairs:
        print(f"\n--- Comparing {sa} vs {sb} ---")
        merged = pd.merge(dfs[sa], dfs[sb], on=["securityid", "date"], suffixes=(f"_{sa}", f"_{sb}"))
        all_dates = sorted(merged["date"].unique())
        print(f"  Merged rows: {len(merged)}")

        for col in alpha_cols:
            res = _compare_pair(merged, col, sa, sb, all_dates)
            res["alpha"] = col
            res["pair"] = f"{sa}_vs_{sb}"
            results.append(res)

            if res.get("status") == "ok":
                flag = " *** MATCH" if abs(res["pearson_r"]) > 0.99 else ""
                print(
                    f"  {col}: pearson={res['pearson_r']:+.4f}  "
                    f"spearman={res['spearman_r']:+.4f}  "
                    f"IC={res.get('ic_mean', float('nan')):+.4f}  "
                    f"mae={res['mae']:.6f}{flag}"
                )

    result_df = pd.DataFrame(results)
    result_df.to_csv(COMPARISON_OUTPUT, index=False)
    print(f"\nComparison saved to {COMPARISON_OUTPUT}")
    return result_df


# ── Summary ─────────────────────────────────────────────────────────────────
def print_summary(comparison_df, pd_timing):
    print("\n" + "=" * 70)
    print("SUMMARY: Three-way comparison (pandas vs alpha-lib vs polars_ta)")
    print("=" * 70)

    # Timing comparison
    pd_ok = pd_timing[
        (pd_timing["status"] == "ok") & (pd_timing["alpha"] != "data_load")
    ]
    print(f"\nPandas timing ({len(pd_ok)} factors):")
    print(f"  Total:  {pd_ok['time_ms'].sum():>10.0f} ms")
    print(f"  Mean:   {pd_ok['time_ms'].mean():>10.1f} ms")
    print(f"  Median: {pd_ok['time_ms'].median():>10.1f} ms")

    # Load other timings
    timing_files = {
        "alpha-lib": PROJECT_ROOT / "al_timing.csv",
        "polars_ta": PROJECT_ROOT / "pt_timing.csv",
    }
    other_timings = {}
    for name, path in timing_files.items():
        if path.exists():
            t = pd.read_csv(path)
            t_ok = t[(t["status"] == "ok") & ~t["alpha"].isin(["data_load", "adv_returns"])]
            other_timings[name] = t_ok
            print(f"\n{name} timing ({len(t_ok)} factors):")
            print(f"  Total:  {t_ok['time_ms'].sum():>10.0f} ms")
            print(f"  Mean:   {t_ok['time_ms'].mean():>10.1f} ms")
            print(f"  Median: {t_ok['time_ms'].median():>10.1f} ms")

    if other_timings:
        print(f"\n{'':15} {'pandas':>12}", end="")
        for name in other_timings:
            print(f" {name:>12}", end="")
        print()

        pd_total = pd_ok["time_ms"].sum()
        print(f"  {'Total':15} {pd_total:>10.0f}ms", end="")
        for name, t_ok in other_timings.items():
            t_total = t_ok["time_ms"].sum()
            print(f" {t_total:>10.0f}ms", end="")
        print()

        print(f"  {'vs pandas':15} {'1.0x':>12}", end="")
        for name, t_ok in other_timings.items():
            t_total = t_ok["time_ms"].sum()
            ratio = pd_total / t_total if t_total > 0 else float("inf")
            print(f" {ratio:>11.1f}x", end="")
        print()

    # Per-pair correlation summary
    for pair in comparison_df["pair"].unique():
        pair_df = comparison_df[(comparison_df["pair"] == pair) & (comparison_df["status"] == "ok")]
        if len(pair_df) == 0:
            continue

        high = pair_df[pair_df["pearson_r"].abs() > 0.99]
        med = pair_df[(pair_df["pearson_r"].abs() > 0.5) & (pair_df["pearson_r"].abs() <= 0.99)]
        low = pair_df[pair_df["pearson_r"].abs() <= 0.5]

        print(f"\n{pair} ({len(pair_df)} factors compared):")
        print(f"  High correlation (|r| > 0.99): {len(high)}")
        print(f"  Medium (0.5 < |r| <= 0.99):   {len(med)}")
        print(f"  Low (|r| <= 0.5):              {len(low)}")

        print(f"  {'Metric':<15} {'Mean':>10} {'Median':>10}")
        print(f"  {'-'*37}")
        for metric in ["pearson_r", "spearman_r", "ic_mean", "mae"]:
            vals = pair_df[metric].dropna()
            if len(vals) > 0:
                print(f"  {metric:<15} {vals.mean():>10.4f} {vals.median():>10.4f}")


def main():
    pd_df, pd_timing = step1_compute_pandas()
    comparison_df = step2_compare(pd_df)
    print_summary(comparison_df, pd_timing)


if __name__ == "__main__":
    main()
