from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_group_research_run_import_does_not_load_page_runtime() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from tools.factors.tester_calc.single_factor_test.group "
                "import research_run as module; "
                "assert callable(module.prepare_group_run_spec); "
                "assert callable(module.execute_group_run_spec); "
                "from tools.factors.tester_calc.single_factor_test.group."
                "research_run.execution import _result_retention_mode; "
                "assert _result_retention_mode({"
                "'retention_mode': 'summary', "
                "'result_retention_mode': 'full'}) == 'full'; "
                "assert 'flask' not in sys.modules; "
                "assert 'server.jobs.report_outputs' not in sys.modules; "
                "assert 'server.services.page_runtime' not in sys.modules"
            ),
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert probe.returncode == 0, probe.stderr
