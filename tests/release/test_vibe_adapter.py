from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

from tools.cli.release.adapters.archive import install_adapter_archive
from tools.cli.release.adapters.contracts import validate_adapter_contract


ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "client-adapters" / "vibe-trading"


def _builder():
    spec = importlib.util.spec_from_file_location(
        "vibe_adapter_builder", ADAPTER / "build_archive.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vibe_adapter_contract_targets_embedded_loopback_ui() -> None:
    contract = validate_adapter_contract(json.loads(
        (ADAPTER / "adapter.json").read_text(encoding="utf-8")
    ))
    assert contract.adapter_id == "vibe-trading"
    assert contract.version == "0.1.11"
    assert contract.ui_url == "http://127.0.0.1:7899"
    assert contract.actions["start"].argv == ("bin/start",)


def test_vibe_adapter_archive_is_deterministic_and_installable(
    tmp_path: Path,
) -> None:
    first = _builder().build(tmp_path / "first.zip")
    second = _builder().build(tmp_path / "second.zip")
    assert first.read_bytes() == second.read_bytes()

    contract = install_adapter_archive(first, tmp_path / "adapters")
    installed = tmp_path / "adapters" / contract.adapter_id
    assert contract.adapter_id == "vibe-trading"
    assert (installed / "bin" / "start").stat().st_mode & 0o111
    with zipfile.ZipFile(first) as archive:
        assert set(archive.namelist()) == {
            "adapter.json", "bin/start", "bin/health", "bin/open", "bin/stop",
        }


def test_vibe_adapter_start_never_downloads_or_invokes_a_shell() -> None:
    source = (ADAPTER / "bin" / "start").read_text(encoding="utf-8")
    assert "os.execv(" in source
    for forbidden in ("pip install", "git clone", "subprocess", "shell=True"):
        assert forbidden not in source


def test_vibe_adapter_uses_user_selected_official_executable(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "vibe-trading"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\nprint(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"executable": str(executable)}),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "FACTORTESTER_ADAPTER_ROOT": str(ADAPTER),
        "FACTORTESTER_ADAPTER_CONFIGURATION_REF": str(config),
        "FACTORTESTER_VIBE_PORT": "17899",
    }

    result = subprocess.run(
        [ADAPTER / "bin" / "start"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(result.stdout) == [
        "serve", "--host", "127.0.0.1", "--port", "17899",
    ]
