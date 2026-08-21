from __future__ import annotations

import hashlib
import json
import shutil
import sys

import pytest

from server.jobs.supplemental.custom_python import (
    SandboxUnavailable,
    run_custom_python,
    validate_source,
)


def _artifact(path, value: object) -> dict[str, object]:
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    return {
        "name": "metrics",
        "path": path,
        "content_hash": hashlib.sha256(raw).hexdigest(),
        "content_type": "application/json",
    }


@pytest.mark.parametrize(
    "source",
    [
        "import os\nresult = os.environ",
        "import subprocess\nresult = subprocess.run(['true'])",
        "result = open('/etc/passwd').read()",
        "result = eval('1 + 1')",
        "result = ().__class__.__mro__",
    ],
)
def test_custom_python_rejects_ambient_capabilities(source: str) -> None:
    with pytest.raises(ValueError):
        validate_source(source)


def test_custom_python_requires_a_result_assignment() -> None:
    with pytest.raises(ValueError, match="result"):
        validate_source("value = 1")


def test_custom_python_reads_declared_artifacts_and_returns_structured_output(
    tmp_path,
) -> None:
    if sys.platform == "darwin" and not shutil.which("sandbox-exec"):
        pytest.skip("macOS sandbox-exec is unavailable")
    if sys.platform.startswith("linux") and not shutil.which("bwrap"):
        pytest.skip("Linux bubblewrap is unavailable")
    artifact = _artifact(tmp_path / "metrics.json", {"returns": [1, 2, 3]})

    output = run_custom_python(
        "data = artifacts.load_json('metrics')\n"
        "result = {'total': sum(data['returns']), 'names': artifacts.list()}",
        [artifact],
        timeout_seconds=5,
    )

    assert output["result"] == {"total": 6, "names": ["metrics"]}
    assert output["logs"] == []


def test_custom_python_never_falls_back_without_an_os_sandbox(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    artifact = _artifact(tmp_path / "metrics.json", {"value": 1})

    with pytest.raises(SandboxUnavailable):
        run_custom_python("result = 1", [artifact])
