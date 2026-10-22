# !/usr/bin/env python3

import time
import polars as pl
from .alpha101_adjusted import Alphas
import argparse

import logging

logger = logging.getLogger("polars_backend")


def parse_args():
  parser = argparse.ArgumentParser()
  parser.add_argument("no", nargs="*", type=int)
  parser.add_argument("-s", "--start", type=int, required=False)
  parser.add_argument("-e", "--end", type=int, required=False)
  parser.add_argument("-v", "--verbose", action="store_true", required=False)
  parser.add_argument(
    "-d", "--data", type=str, required=False, default="dataPerformance.csv"
  )
  return parser.parse_args()


def setup_context(data_path: str) -> tuple[Alphas, int]:
  logger.info("Loading data")
  t1 = time.time()
  # Use eager execution for data loading to match pandas behavior roughly
  # and ensure IO is separate from calc
  data = pl.read_csv(data_path)
  # data is likely long format: tradetime, securityid, ...
  # Ensure types if needed, but read_csv is usually good.
  # Sorting might be required for rolling operations if not sorted
  data = data.sort(["securityid", "tradetime"])

  ctx = Alphas(data)
  t2 = time.time()
  logger.info("Data loaded in %f seconds", t2 - t1)
  return ctx, int((t2 - t1) * 1000)


nofunc = set(
  [48, 56, 58, 59, 63, 67, 69, 70, 76, 79, 80, 82, 87, 89, 90, 91, 93, 97, 100]
)


def main(args):
  ctx, load_time = setup_context(args.data)

  if len(args.no) == 0:
    start = args.start or 1
    end = args.end or 102
    args.no = [i for i in filter(lambda x: x not in nofunc, range(start, end))]

  results = [("data", load_time, 0)]
  for no in args.no:
    t1 = time.time()
    fn_name = f"alpha{no:03d}"
    logger.info("Computing alpha %s", fn_name)
    fn = getattr(ctx, fn_name)
    # result should be a DataFrame with 'alpha' column (or similar)
    # We need to extract the value for a specific stock (sz000001) at the last timestamp to match pd_
    res_df = fn()
    t2 = time.time()
    logger.info("Alpha %s computed in %f seconds", fn_name, t2 - t1)

    # Extract verification value
    # Filter for sz000001 and take last
    # Assuming columns are [tradetime, securityid, alpha_result]
    # We need to filter.
    # To be faster, we might not want to do this filter inside the timing block?
    # But pd_ includes `res["sz000001"]` (which is a Series lookup) in the timing?
    # Actually pd_ code:
    # t1 = time.time(); fn(ctx); t2 = time.time()
    # Then `res["sz000001"]` access is AFTER timing.
    # So we should exclude extraction from timing.

    # Result extraction
    # Filter for sz000001 and take the last valid value to match pd_ behavior likely
    # pd_ code: res["sz000001"].iloc[-1]
    # We should get the same timestamp as pandas would.
    # Assuming the data is sorted by time, taking the last row for the security is correct.

    val = 0.0
    try:
      val_row = res_df.filter(pl.col("securityid") == "sz000001").tail(1)
      if not val_row.is_empty():
        # Assumes the alpha column is named "alpha" from _exec
        val = val_row.select(pl.col("alpha")).item(0, 0)
    except Exception as e:
      logger.error(f"Error extracting result for {fn_name}: {e}")

    if args.verbose:
      print(val)
    results.append((f"#{no:03d}", int((t2 - t1) * 1000), val))

  import pandas as pd

  df = pd.DataFrame(results, columns=["no", "polarsTime", "polarsValue"])
  df.set_index("no", inplace=True)
  return df


if __name__ == "__main__":
  FORMAT = "%(levelname)s %(name)s %(asctime)-15s %(filename)s:%(lineno)d %(message)s"
  logging.basicConfig(level=logging.INFO, format=FORMAT)
  args = parse_args()
  df = main(args)
  print(df.to_string())
