#!/usr/bin/env python3
"""
Benchmark py-alpha-lib Alpha 101 factors against ground truth from parquet exports.

Steps:
1. Extract ground truth factor values from parquet files -> gt_alpha101.csv
2. Compute factors using py-alpha-lib with timing -> al_alpha101.csv + al_timing.csv
3. Statistical comparison between gt and al -> comparison_results.csv

Usage:
    python benchmark_alpha101.py
"""

import pandas as pd
import numpy as np
import time
import sys
import warnings
from pathlib import Path
from scipy import stats

warnings.filterwarnings("ignore", category=RuntimeWarning)

# Add examples path for alpha-lib imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "examples" / "wq101"))

import alpha
from al.alpha101_context import ExecContext
from al import alpha101

# ── Config ──────────────────────────────────────────────────────────────────
DATA_PATH = PROJECT_ROOT / "dataPerformance.csv"
PARQUET_DIR = Path("/home/null/data/cn_stock_factors_alpha_101_exports")
GT_OUTPUT = PROJECT_ROOT / "gt_alpha101.csv"
AL_OUTPUT = PROJECT_ROOT / "al_alpha101.csv"
TIMING_OUTPUT = PROJECT_ROOT / "al_timing.csv"
COMPARISON_OUTPUT = PROJECT_ROOT / "comparison_results.csv"

UNSUPPORTED = {48, 56, 58, 59, 63, 67, 69, 70, 76, 79, 80, 82, 87, 89, 90, 91, 93, 97, 100}
ALPHA_COLS = [f"alpha_{i:03d}" for i in range(1, 102)]


def instrument_to_securityid(instrument: str) -> str:
    """000001.SZ -> sz000001"""
    code, exchange = instrument.split(".")
    return exchange.lower() + code


# ── Step 1: Extract ground truth ────────────────────────────────────────────
def step1_extract_gt():
    print("=" * 70)
    print("Step 1: Extracting ground truth from parquet files")
    print("=" * 70)

    # Load CSV to get valid (securityid, date) pairs
    csv_data = pd.read_csv(DATA_PATH, usecols=["securityid", "tradetime"])
    csv_securities = set(csv_data["securityid"].unique())
    csv_data["date"] = pd.to_datetime(
        csv_data["tradetime"].str[:10].str.replace(".", "-", regex=False)
    )
    csv_dates = set(csv_data["date"].unique())

    # Load all 2010 parquet files
    parquet_files = sorted(PARQUET_DIR.glob("cn_stock_factors_alpha_101_2010*.parquet"))
    print(f"Loading {len(parquet_files)} parquet files...")

    gt = pd.concat([pd.read_parquet(f) for f in parquet_files], ignore_index=True)
    print(f"Total parquet rows: {len(gt)}")

    # Convert instrument format and filter
    gt["securityid"] = gt["instrument"].apply(instrument_to_securityid)
    gt = gt[gt["securityid"].isin(csv_securities) & gt["date"].isin(csv_dates)]
    print(
        f"After filtering: {len(gt)} rows, "
        f"{gt['securityid'].nunique()} securities, "
        f"{gt['date'].nunique()} dates"
    )

    gt_out = gt[["securityid", "date"] + ALPHA_COLS].copy()
    gt_out = gt_out.sort_values(["securityid", "date"]).reset_index(drop=True)
    gt_out.to_csv(GT_OUTPUT, index=False)
    print(f"Saved to {GT_OUTPUT} ({gt_out.shape})")
    return gt_out


# ── Step 2: Compute with alpha-lib ─────────────────────────────────────────
def step2_compute_al():
    print("\n" + "=" * 70)
    print("Step 2: Computing factors with py-alpha-lib")
    print("=" * 70)

    # Load data (same as examples/wq101/al/__init__.py)
    t0 = time.time()
    data = pd.read_csv(DATA_PATH)
    df = data.set_index(["securityid", "tradetime"])
    security_count = df.index.get_level_values("securityid").nunique()
    trade_count = df.index.get_level_values("tradetime").nunique()
    alpha.set_ctx(groups=security_count)
    ctx = ExecContext(df)
    load_time_ms = (time.time() - t0) * 1000
    print(
        f"Data loaded in {load_time_ms:.0f}ms "
        f"({security_count} securities x {trade_count} trades)"
    )

    # Prepare output with (securityid, date) index
    data["date"] = pd.to_datetime(
        data["tradetime"].str[:10].str.replace(".", "-", regex=False)
    )
    al_out = data[["securityid", "date"]].copy()

    timing = [("data_load", load_time_ms, "ok")]

    for no in range(1, 102):
        col = f"alpha_{no:03d}"
        if no in UNSUPPORTED:
            timing.append((col, None, "unsupported"))
            continue

        try:
            fn = getattr(alpha101, f"alpha_{no:03d}")
            t1 = time.time()
            v = fn(ctx)
            elapsed_ms = (time.time() - t1) * 1000
            al_out[col] = v
            timing.append((col, elapsed_ms, "ok"))
            print(f"  Alpha #{no:03d}: {elapsed_ms:8.1f}ms")
        except Exception as e:
            timing.append((col, None, f"error: {e}"))
            print(f"  Alpha #{no:03d}: ERROR - {e}")

    al_out.to_csv(AL_OUTPUT, index=False)
    print(f"\nSaved to {AL_OUTPUT} ({al_out.shape})")

    timing_df = pd.DataFrame(timing, columns=["alpha", "time_ms", "status"])
    timing_df.to_csv(TIMING_OUTPUT, index=False)
    print(f"Timing saved to {TIMING_OUTPUT}")

    return al_out, timing_df


# ── Step 3: Statistical comparison ─────────────────────────────────────────
def step3_compare(gt_df, al_df):
    print("\n" + "=" * 70)
    print("Step 3: Statistical comparison (gt vs alpha-lib)")
    print("=" * 70)

    # Merge on (securityid, date) — only overlapping rows
    gt_df = gt_df.copy()
    al_df = al_df.copy()
    gt_df["date"] = pd.to_datetime(gt_df["date"])
    al_df["date"] = pd.to_datetime(al_df["date"])
    merged = pd.merge(gt_df, al_df, on=["securityid", "date"], suffixes=("_gt", "_al"))
    print(f"Merged rows: {len(merged)} (overlap between gt and al)")

    all_dates = sorted(merged["date"].unique())
    results = []

    for col in ALPHA_COLS:
        gt_col, al_col = f"{col}_gt", f"{col}_al"

        if gt_col not in merged.columns or al_col not in merged.columns:
            results.append({"alpha": col, "status": "missing_column"})
            continue

        gt_vals = merged[gt_col].values.astype(np.float64)
        al_vals = merged[al_col].values.astype(np.float64)

        # Clean NaN/Inf
        mask = np.isfinite(gt_vals) & np.isfinite(al_vals)
        gt_clean = gt_vals[mask]
        al_clean = al_vals[mask]
        n = len(gt_clean)

        if n < 30:
            results.append(
                {"alpha": col, "status": f"insufficient_data (n={n})", "n_valid": n}
            )
            continue

        # ── Overall correlation ──
        pearson_r, pearson_p = stats.pearsonr(gt_clean, al_clean)
        spearman_r, spearman_p = stats.spearmanr(gt_clean, al_clean)

        # ── Kendall tau (sample if too large) ──
        if n > 50000:
            idx = np.random.default_rng(42).choice(n, 50000, replace=False)
            kendall_tau, kendall_p = stats.kendalltau(gt_clean[idx], al_clean[idx])
        else:
            kendall_tau, kendall_p = stats.kendalltau(gt_clean, al_clean)

        # ── Error metrics ──
        mae = np.mean(np.abs(gt_clean - al_clean))
        rmse = np.sqrt(np.mean((gt_clean - al_clean) ** 2))
        gt_std = np.std(gt_clean)
        al_std = np.std(al_clean)

        # ── KS test (distribution similarity) ──
        ks_stat, ks_p = stats.ks_2samp(gt_clean, al_clean)

        # ── Paired t-test (mean difference) ──
        t_stat, t_p = stats.ttest_rel(gt_clean, al_clean)

        # ── Cross-sectional rank IC (per-date Spearman) ──
        ic_list = []
        for dt in all_dates:
            dt_mask = (merged["date"] == dt).values & mask
            if dt_mask.sum() < 10:
                continue
            g = gt_vals[dt_mask]
            a = al_vals[dt_mask]
            r, _ = stats.spearmanr(g, a)
            if np.isfinite(r):
                ic_list.append(r)

        ic_mean = np.mean(ic_list) if ic_list else np.nan
        ic_std = np.std(ic_list) if ic_list else np.nan
        icir = ic_mean / ic_std if ic_std > 0 else np.nan
        ic_n = len(ic_list)

        row = {
            "alpha": col,
            "status": "ok",
            "n_valid": n,
            "pearson_r": round(pearson_r, 6),
            "pearson_p": pearson_p,
            "spearman_r": round(spearman_r, 6),
            "spearman_p": spearman_p,
            "kendall_tau": round(kendall_tau, 6),
            "kendall_p": kendall_p,
            "mae": round(mae, 6),
            "rmse": round(rmse, 6),
            "gt_std": round(gt_std, 6),
            "al_std": round(al_std, 6),
            "ks_stat": round(ks_stat, 6),
            "ks_p": ks_p,
            "ttest_stat": round(t_stat, 4),
            "ttest_p": t_p,
            "ic_mean": round(ic_mean, 6) if np.isfinite(ic_mean) else np.nan,
            "ic_std": round(ic_std, 6) if np.isfinite(ic_std) else np.nan,
            "icir": round(icir, 4) if np.isfinite(icir) else np.nan,
            "ic_n_dates": ic_n,
        }
        results.append(row)

        print(
            f"  {col}: pearson={pearson_r:+.4f}  spearman={spearman_r:+.4f}  "
            f"kendall={kendall_tau:+.4f}  IC={ic_mean:+.4f}  ICIR={icir:+.4f}  "
            f"n={n}"
        )

    result_df = pd.DataFrame(results)
    result_df.to_csv(COMPARISON_OUTPUT, index=False)
    print(f"\nComparison saved to {COMPARISON_OUTPUT}")
    return result_df


# ── Summary ─────────────────────────────────────────────────────────────────
def print_summary(comparison_df, timing_df):
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    ok = comparison_df[comparison_df["status"] == "ok"]
    if len(ok) == 0:
        print("No factors successfully compared.")
        return

    print(f"\nFactors compared: {len(ok)} / 101")
    print(f"  Unsupported:    {len(comparison_df[comparison_df['status'].str.contains('missing', na=False) | comparison_df['status'].str.contains('insufficient', na=False)])}")

    print(f"\n{'Metric':<20} {'Mean':>10} {'Median':>10} {'Min':>10} {'Max':>10}")
    print("-" * 62)
    for metric in ["pearson_r", "spearman_r", "kendall_tau", "ic_mean", "icir"]:
        vals = ok[metric].dropna()
        if len(vals) > 0:
            print(
                f"  {metric:<18} {vals.mean():>10.4f} {vals.median():>10.4f} "
                f"{vals.min():>10.4f} {vals.max():>10.4f}"
            )

    # Timing
    ok_timing = timing_df[(timing_df["status"] == "ok") & (timing_df["alpha"] != "data_load")]
    if len(ok_timing) > 0:
        print(f"\nAlpha-lib timing ({len(ok_timing)} factors):")
        print(f"  Total:  {ok_timing['time_ms'].sum():>8.0f} ms")
        print(f"  Mean:   {ok_timing['time_ms'].mean():>8.1f} ms")
        print(f"  Median: {ok_timing['time_ms'].median():>8.1f} ms")
        print(f"  Max:    {ok_timing['time_ms'].max():>8.1f} ms ({ok_timing.loc[ok_timing['time_ms'].idxmax(), 'alpha']})")
        print(f"  Min:    {ok_timing['time_ms'].min():>8.1f} ms ({ok_timing.loc[ok_timing['time_ms'].idxmin(), 'alpha']})")


def main():
    gt_df = step1_extract_gt()
    al_df, timing_df = step2_compute_al()
    comparison_df = step3_compare(gt_df, al_df)
    print_summary(comparison_df, timing_df)


if __name__ == "__main__":
    main()
