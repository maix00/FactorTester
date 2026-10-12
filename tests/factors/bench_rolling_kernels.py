"""Run the batch and live rolling-kernel performance checks together."""

from __future__ import annotations

from rolling_benchmarks.batch import main as benchmark_batch
from rolling_benchmarks.extrema import main as benchmark_extrema
from rolling_benchmarks.incremental import main as benchmark_incremental
from rolling_benchmarks.window import main as benchmark_window


def main() -> None:
    benchmark_batch()
    benchmark_incremental()
    benchmark_window()
    benchmark_extrema()


if __name__ == "__main__":
    main()
