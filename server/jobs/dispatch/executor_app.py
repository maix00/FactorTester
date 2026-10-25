"""Default executor router for Celery workers.

Set ``FACTORTESTER_NAUTILUS_EXECUTOR=server.jobs.dispatch.executor_app:executor``
to route backtests to the Nautilus adapter and the remaining Job kinds to their
existing process runners.
"""

from __future__ import annotations

from server.modules.single_factor_test.process_runners import (
    run_factor_evaluation,
    run_factor_type_analysis,
    run_ic,
)
from server.services.nautilus_bridge.job_executor import NautilusJobExecutor

from .executors import JobExecutorRouter, ProcessRunnerExecutor

executor = JobExecutorRouter(
    backtest=NautilusJobExecutor(),
    process=ProcessRunnerExecutor({
        "ic": run_ic,
        "factor_evaluation": run_factor_evaluation,
        "factor_type_analysis": run_factor_type_analysis,
    }),
)
