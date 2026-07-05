"""Update LocalCNFutures data_dayk.parquet from AKShare daily futures data."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in (None, ""):
    _root = Path(__file__).resolve().parents[3]
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from sources.LocalCNFutures.daily_update import DEFAULT_MARKETS, update_data_dayk_from_akshare
from sources.LocalCNFutures.scripts.generate_main import generate_main_contract_series


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="从 AKShare 增量补全 LocalCNFutures data_dayk.parquet。"
    )
    parser.add_argument("--start-date", help="起始日期，例如 20260109；默认从现有 data_dayk 最大日期后一天开始")
    parser.add_argument("--end-date", help="结束日期，例如 20260112；默认今天")
    parser.add_argument(
        "--market",
        action="append",
        choices=DEFAULT_MARKETS,
        help="交易所，可重复；默认全部交易所",
    )
    parser.add_argument("--dry-run", action="store_true", help="只抓取和校验，不写 parquet")
    parser.add_argument("--strict", action="store_true", help="任一交易所抓取失败即报错")
    parser.add_argument("--strict-validation", action="store_true", help="日线 close 与本地分钟线 close 不一致时报错")
    parser.add_argument("--generate-main", action="store_true", help="写入日线后调用 GenerateMain 更新主力日线/分钟线")
    parser.add_argument("--rebuild-minute-product", action="store_true", help="GenerateMain 时重建分钟合约分文件")
    args = parser.parse_args(argv)

    markets = tuple(args.market or DEFAULT_MARKETS)
    report = update_data_dayk_from_akshare(
        start_date=args.start_date,
        end_date=args.end_date,
        markets=markets,
        dry_run=args.dry_run,
        strict=args.strict,
        strict_validation=args.strict_validation,
        show_progress=True,
    )
    print(f"data_dayk: {report.path}")
    print(f"range: {report.start_date.date()} -> {report.end_date.date()} markets={','.join(report.markets)}")
    print(f"fetched_rows={report.fetched_rows} written_rows={report.written_rows} dry_run={args.dry_run}")
    if report.validation_mismatches:
        print("minute validation mismatches:")
        for item in report.validation_mismatches[:10]:
            print(f"  {item}")
    if report.warnings:
        print("warnings:")
        for warning in report.warnings[:20]:
            print(f"  {warning}")

    if args.generate_main and not args.dry_run:
        generate_main_contract_series(
            rebuild_roller_info=True,
            rebuild_minute_product=bool(args.rebuild_minute_product),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
