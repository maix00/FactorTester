"""Run the batch and live rolling-kernel performance checks together."""

from __future__ import annotations

from rolling_benchmarks.batch import main as benchmark_batch
from rolling_benchmarks.incremental import main as benchmark_incremental


def main() -> None:
    benchmark_batch()
    benchmark_incremental()


if __name__ == "__main__":
    main()
