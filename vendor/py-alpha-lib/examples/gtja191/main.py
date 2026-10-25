import urllib.request
import zipfile
from pathlib import Path
import logging
import argparse
import al
import pandas as pd

FORMAT = "%(levelname)s %(name)s %(asctime)-15s  %(message)s"

logging.basicConfig(level=logging.INFO, format=FORMAT)

logger = logging.getLogger("wq101")

data_file = Path("dataPerformance.csv")


def download_data():
  if data_file.exists():
    logger.info("data file already exists")
    return

  logger.info("downloading data")

  # use it when you can access github
  url = "https://github.com/dolphindb/DolphinDBModules/raw/refs/heads/master/wq101alpha/test/dataPerformance.zip"

  # use it when you in China
  url = "https://cdn.dolphindb.cn/downloads/docs/101_data.zip"

  resp = urllib.request.urlopen(url)
  with open("dataPerformance.zip", "wb") as f:
    f.write(resp.read())

  logger.info("extracting data")
  with zipfile.ZipFile("dataPerformance.zip", "r") as zip_ref:
    zip_ref.extractall(".")

  logger.info("data downloaded")


def parse_args():
  parser = argparse.ArgumentParser()
  parser.add_argument(
    "no", nargs="*", type=int, help="alpha numbers to run, e.g., 1 2 3"
  )
  parser.add_argument(
    "-s", "--start", type=int, required=False, help="start alpha number"
  )
  parser.add_argument("-e", "--end", type=int, required=False, help="end alpha number")
  parser.add_argument(
    "-v",
    "--verbose",
    action="store_true",
    required=False,
    help="enable verbose logging",
  )
  parser.add_argument(
    "-d",
    "--data",
    type=str,
    required=False,
    default="dataPerformance.csv",
    help="data file path",
  )
  parser.add_argument(
    "-o", "--output", type=str, required=False, help="save output to file"
  )
  parser.add_argument(
    "--with-al", action="store_true", default=True, help="run alpha-lib implementation"
  )
  return parser.parse_args()


def main():
  args = parse_args()
  download_data()
  results = []
  if args.with_al:
    results.append(al.main(args))

  if len(results) == 0:
    return

  df = pd.concat(results, axis=1)
  if len(results) == 2:
    df["speedup"] = (df["pandasTime"] / df["alphaLibTime"]).astype(int)
  if args.output:
    df.to_csv(args.output)
  else:
    print(df.to_string())


if __name__ == "__main__":
  main()
