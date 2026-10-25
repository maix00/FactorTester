#!/usr/bin/env python3
"""
Compute Alpha 101 using polars_ta + expr_codegen (alpha_examples approach),
then compare with py-alpha-lib results.

Both compute on the same dataPerformance.csv data, making this a valid
implementation correctness comparison.
"""

import logging
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
from scipy import stats

warnings.filterwarnings("ignore", category=RuntimeWarning)

# Suppress noisy codegen logging
logging.getLogger("expr_codegen").setLevel(logging.WARNING)

# ── Paths ───────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = PROJECT_ROOT / "dataPerformance.csv"
ALPHA101_EXPR = Path(
    "/home/null/quant/reference/因子计算引擎/alpha_examples/transformer/alpha101_out.txt"
)
AL_CSV = PROJECT_ROOT / "al_alpha101.csv"
PT_OUTPUT = PROJECT_ROOT / "pt_alpha101.csv"
PT_TIMING = PROJECT_ROOT / "pt_timing.csv"
COMPARISON_OUTPUT = PROJECT_ROOT / "comparison_al_vs_pt.csv"


# ── Step 1: Compute Alpha 101 with polars_ta ────────────────────────────────
def step1_compute_polars_ta():
    from expr_codegen import codegen_exec
    import more_itertools  # noqa: F401

    print("=" * 70)
    print("Step 1: Computing Alpha 101 with polars_ta + expr_codegen")
    print("=" * 70)

    # Load data
    t0 = time.time()
    df = pl.read_csv(str(DATA_PATH))

    # Rename columns to match polars_ta conventions
    df = df.rename({
        "tradetime": "date",
        "securityid": "asset",
        "vol": "VOLUME",
        "open": "OPEN",
        "high": "HIGH",
        "low": "LOW",
        "close": "CLOSE",
        "vwap": "VWAP",
        "indclass": "indclass",
        "cap": "CAP",
    })

    # Parse date: "2010.01.04T00:00:00.000" -> date
    df = df.with_columns(
        pl.col("date")
        .str.slice(0, 10)
        .str.replace_all(r"\.", "-")
        .str.to_date("%Y-%m-%d")
        .alias("date")
    )

    # AMOUNT not available, use VOLUME (consistent with py-alpha-lib's ADV)
    df = df.with_columns(pl.col("VOLUME").alias("AMOUNT"))

    load_time_ms = (time.time() - t0) * 1000
    print(f"Data loaded in {load_time_ms:.0f}ms ({df.shape})")
    print(f"  Securities: {df['asset'].n_unique()}, Dates: {df['date'].n_unique()}")

    # Pre-compute ADV and RETURNS
    def _code_block_():
        ADV5 = ts_mean(AMOUNT, 5)  # noqa: F841, F821
        ADV10 = ts_mean(AMOUNT, 10)  # noqa: F841, F821
        ADV15 = ts_mean(AMOUNT, 15)  # noqa: F841, F821
        ADV20 = ts_mean(AMOUNT, 20)  # noqa: F841, F821
        ADV30 = ts_mean(AMOUNT, 30)  # noqa: F841, F821
        ADV40 = ts_mean(AMOUNT, 40)  # noqa: F841, F821
        ADV50 = ts_mean(AMOUNT, 50)  # noqa: F841, F821
        ADV60 = ts_mean(AMOUNT, 60)  # noqa: F841, F821
        ADV81 = ts_mean(AMOUNT, 81)  # noqa: F841, F821
        ADV120 = ts_mean(AMOUNT, 120)  # noqa: F841, F821
        ADV150 = ts_mean(AMOUNT, 150)  # noqa: F841, F821
        ADV180 = ts_mean(AMOUNT, 180)  # noqa: F841, F821
        RETURNS = ts_returns(CLOSE, 1)  # noqa: F841, F821

    t1 = time.time()
    df = codegen_exec(df, _code_block_, over_null="partition_by")
    prep_ms = (time.time() - t1) * 1000
    print(f"ADV/RETURNS pre-computed in {prep_ms:.0f}ms")

    # Read alpha expressions
    with open(ALPHA101_EXPR, "r") as f:
        all_lines = [line.strip() for line in f if line.strip()]

    # Parse alpha names from each line
    line_info = []
    for line in all_lines:
        alpha_name = line.split("=")[0].strip()
        no = int(alpha_name.split("_")[1])
        line_info.append((no, f"alpha_{no:03d}", line))

    # Compute one by one for individual timing
    timing = [("data_load", load_time_ms, "ok"), ("adv_returns", prep_ms, "ok")]
    computed_alphas = []

    for no, col_name, line in line_info:
        try:
            t1 = time.time()
            df = codegen_exec(df, line, over_null="partition_by")
            elapsed_ms = (time.time() - t1) * 1000
            timing.append((col_name, elapsed_ms, "ok"))
            computed_alphas.append(col_name)
            print(f"  Alpha #{no:03d}: {elapsed_ms:8.1f}ms")
        except Exception as e:
            err_msg = str(e).split("\n")[0][:80]
            timing.append((col_name, None, f"error: {err_msg}"))
            print(f"  Alpha #{no:03d}: ERROR - {err_msg}")

    # Extract results
    keep_cols = ["asset", "date"] + [c for c in computed_alphas if c in df.columns]
    pt_df = df.select(keep_cols).to_pandas()
    pt_df.rename(columns={"asset": "securityid"}, inplace=True)
    pt_df.to_csv(PT_OUTPUT, index=False)
    print(f"\nSaved to {PT_OUTPUT} ({pt_df.shape})")

    timing_df = pd.DataFrame(timing, columns=["alpha", "time_ms", "status"])
    timing_df.to_csv(PT_TIMING, index=False)
    print(f"Timing saved to {PT_TIMING}")

    return pt_df, timing_df


# ── Step 2: Compare polars_ta vs alpha-lib ──────────────────────────────────
def step2_compare(pt_df):
    print("\n" + "=" * 70)
    print("Step 2: Statistical comparison (alpha-lib vs polars_ta)")
    print("=" * 70)

    if not AL_CSV.exists():
        print(f"ERROR: {AL_CSV} not found. Run benchmark_alpha101.py first.")
        return None

    al_df = pd.read_csv(AL_CSV)
    al_df["date"] = pd.to_datetime(al_df["date"])
    pt_df["date"] = pd.to_datetime(pt_df["date"])

    merged = pd.merge(al_df, pt_df, on=["securityid", "date"], suffixes=("_al", "_pt"))
    print(f"Merged rows: {len(merged)}")

    all_dates = sorted(merged["date"].unique())
    alpha_cols = [f"alpha_{i:03d}" for i in range(1, 102)]
    results = []

    for col in alpha_cols:
        al_col, pt_col = f"{col}_al", f"{col}_pt"

        if al_col not in merged.columns or pt_col not in merged.columns:
            has_al = al_col in merged.columns
            has_pt = pt_col in merged.columns
            status = f"missing: al={'Y' if has_al else 'N'} pt={'Y' if has_pt else 'N'}"
            results.append({"alpha": col, "status": status})
            continue

        al_vals = merged[al_col].values.astype(np.float64)
        pt_vals = merged[pt_col].values.astype(np.float64)

        mask = np.isfinite(al_vals) & np.isfinite(pt_vals)
        al_clean = al_vals[mask]
        pt_clean = pt_vals[mask]
        n = len(al_clean)

        if n < 30:
            results.append({"alpha": col, "status": f"insufficient (n={n})", "n_valid": n})
            continue

        # Correlations
        pearson_r, pearson_p = stats.pearsonr(al_clean, pt_clean)
        spearman_r, spearman_p = stats.spearmanr(al_clean, pt_clean)

        # Kendall (sampled for large n)
        if n > 50000:
            idx = np.random.default_rng(42).choice(n, 50000, replace=False)
            kendall_tau, kendall_p = stats.kendalltau(al_clean[idx], pt_clean[idx])
        else:
            kendall_tau, kendall_p = stats.kendalltau(al_clean, pt_clean)

        # Error metrics
        mae = np.mean(np.abs(al_clean - pt_clean))
        rmse = np.sqrt(np.mean((al_clean - pt_clean) ** 2))

        # KS test
        ks_stat, ks_p = stats.ks_2samp(al_clean, pt_clean)

        # Cross-sectional IC (per-date Spearman)
        ic_list = []
        for dt in all_dates:
            dt_mask = (merged["date"] == dt).values & mask
            if dt_mask.sum() < 10:
                continue
            a = al_vals[dt_mask]
            p = pt_vals[dt_mask]
            r, _ = stats.spearmanr(a, p)
            if np.isfinite(r):
                ic_list.append(r)

        ic_mean = np.mean(ic_list) if ic_list else np.nan
        ic_std = np.std(ic_list) if ic_list else np.nan
        icir = ic_mean / ic_std if ic_std > 0 else np.nan

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
            "ks_stat": round(ks_stat, 6),
            "ks_p": ks_p,
            "ic_mean": round(ic_mean, 6) if np.isfinite(ic_mean) else np.nan,
            "ic_std": round(ic_std, 6) if np.isfinite(ic_std) else np.nan,
            "icir": round(icir, 4) if np.isfinite(icir) else np.nan,
        }
        results.append(row)

        flag = " *** MATCH" if abs(pearson_r) > 0.99 else ""
        print(
            f"  {col}: pearson={pearson_r:+.4f}  spearman={spearman_r:+.4f}  "
            f"kendall={kendall_tau:+.4f}  IC={ic_mean:+.4f}  mae={mae:.6f}{flag}"
        )

    result_df = pd.DataFrame(results)
    result_df.to_csv(COMPARISON_OUTPUT, index=False)
    print(f"\nComparison saved to {COMPARISON_OUTPUT}")
    return result_df


# ── Summary ─────────────────────────────────────────────────────────────────
def print_summary(comparison_df, pt_timing, al_timing_path):
    print("\n" + "=" * 70)
    print("SUMMARY: alpha-lib vs polars_ta (same data)")
    print("=" * 70)

    ok = comparison_df[comparison_df["status"] == "ok"]
    if len(ok) == 0:
        print("No factors successfully compared.")
        return

    high_corr = ok[ok["pearson_r"].abs() > 0.99]
    med_corr = ok[(ok["pearson_r"].abs() > 0.5) & (ok["pearson_r"].abs() <= 0.99)]
    low_corr = ok[ok["pearson_r"].abs() <= 0.5]

    print(f"\nFactors compared: {len(ok)}")
    print(f"  High correlation (|r| > 0.99): {len(high_corr)}")
    print(f"  Medium correlation (0.5 < |r| <= 0.99): {len(med_corr)}")
    print(f"  Low correlation (|r| <= 0.5): {len(low_corr)}")

    print(f"\n{'Metric':<20} {'Mean':>10} {'Median':>10} {'Min':>10} {'Max':>10}")
    print("-" * 62)
    for metric in ["pearson_r", "spearman_r", "kendall_tau", "ic_mean", "mae"]:
        vals = ok[metric].dropna()
        if len(vals) > 0:
            print(
                f"  {metric:<18} {vals.mean():>10.4f} {vals.median():>10.4f} "
                f"{vals.min():>10.4f} {vals.max():>10.4f}"
            )

    # Timing comparison
    pt_ok = pt_timing[
        (pt_timing["status"] == "ok")
        & ~pt_timing["alpha"].isin(["data_load", "adv_returns"])
    ]
    if al_timing_path.exists():
        al_timing = pd.read_csv(al_timing_path)
        al_ok = al_timing[
            (al_timing["status"] == "ok") & (al_timing["alpha"] != "data_load")
        ]

        print(
            f"\nTiming comparison ({len(pt_ok)} polars_ta vs {len(al_ok)} alpha-lib):"
        )
        print(f"  {'':15} {'polars_ta':>12} {'alpha-lib':>12} {'ratio':>10}")
        pt_total = pt_ok["time_ms"].sum()
        al_total = al_ok["time_ms"].sum()
        pt_mean = pt_ok["time_ms"].mean()
        al_mean = al_ok["time_ms"].mean()
        pt_med = pt_ok["time_ms"].median()
        al_med = al_ok["time_ms"].median()
        print(
            f"  {'Total':15} {pt_total:>10.0f}ms {al_total:>10.0f}ms {pt_total/al_total:>9.1f}x"
        )
        print(
            f"  {'Mean':15} {pt_mean:>10.1f}ms {al_mean:>10.1f}ms {pt_mean/al_mean:>9.1f}x"
        )
        print(
            f"  {'Median':15} {pt_med:>10.1f}ms {al_med:>10.1f}ms {pt_med/al_med:>9.1f}x"
        )

    if len(high_corr) > 0:
        print(f"\nFactors with HIGH agreement (|pearson_r| > 0.99):")
        for _, r in high_corr.iterrows():
            print(f"  {r['alpha']}: r={r['pearson_r']:+.6f}  mae={r['mae']:.6f}")

    if len(low_corr) > 0:
        print(f"\nFactors with LOW agreement (|pearson_r| <= 0.5):")
        for _, r in low_corr.iterrows():
            print(f"  {r['alpha']}: r={r['pearson_r']:+.6f}  mae={r['mae']:.6f}")


def main():
    pt_df, pt_timing = step1_compute_polars_ta()
    comparison_df = step2_compare(pt_df)
    if comparison_df is not None:
        print_summary(comparison_df, pt_timing, PROJECT_ROOT / "al_timing.csv")


if __name__ == "__main__":
    main()
