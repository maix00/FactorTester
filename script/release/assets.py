"""Build immutable client release assets."""

from __future__ import annotations

from pathlib import Path
from hashlib import sha256
import json
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile


DEPENDENCIES = (
    "click==8.4.1",
    "markdown-it-py==4.2.0",
    "mdurl==0.1.2",
    "plotext==5.3.2",
    "pygments==2.20.0",
    "rich==15.0.0",
)
PYINSTALLER_VERSION = "6.21.0"


def build_python_assets(repo: Path, output: Path) -> list[Path]:
    wheels = [
        _build_wheel(repo / "tools" / "cli", "factortester", output),
        _build_wheel(
            repo / "tools" / "cli" / "agent-harness",
            "cli_anything_factortester_research",
            output,
        ),
    ]
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--no-deps",
            "--dest",
            str(output),
            *DEPENDENCIES,
        ],
        check=True,
    )
    return wheels + sorted(
        path for path in output.glob("*.whl") if path not in wheels
    )


def build_app_archive(app: Path, output: Path) -> Path:
    if not (app / "Contents" / "Info.plist").is_file():
        raise ValueError(f"macOS application is incomplete: {app}")
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(app.rglob("*")):
            if source.is_symlink():
                raise ValueError(f"macOS application contains symlink: {source}")
            relative = Path(app.name) / source.relative_to(app)
            name = str(relative) + ("/" if source.is_dir() else "")
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o40755 if source.is_dir() else 0o100755
            if source.is_file() and not source.stat().st_mode & 0o111:
                mode = 0o100644
            info.external_attr = mode << 16
            archive.writestr(info, b"" if source.is_dir() else source.read_bytes())
    return output


def build_installer_dmg(app: Path, output: Path) -> Path:
    """Build the familiar drag-to-Applications macOS installer image.

    The DMG is a human-facing release asset. It intentionally stays outside
    the signed component manifest: the app archive in that manifest remains
    the transactional update payload.
    """
    if sys.platform != "darwin":
        raise ValueError("macOS installer images can only be built on macOS")
    if not (app / "Contents" / "Info.plist").is_file():
        raise ValueError(f"macOS application is incomplete: {app}")
    with tempfile.TemporaryDirectory(
        prefix="factortester-installer-"
    ) as raw:
        root = Path(raw)
        shutil.copytree(app, root / app.name)
        (root / "Applications").symlink_to("/Applications")
        subprocess.run(
            [
                "hdiutil",
                "create",
                "-volname",
                "FactorTester-Client",
                "-srcfolder",
                str(root),
                "-format",
                "UDZO",
                "-ov",
                str(output),
            ],
            check=True,
            capture_output=True,
        )
    return output


def embed_client_runtime(
    repo: Path,
    app: Path,
    *,
    version: str,
    source_revision: str,
) -> Path:
    """Embed a provider-neutral CLI runtime and approved adapters in the app."""
    resources = app / "Contents" / "Resources" / "FactorTester"
    if resources.exists():
        shutil.rmtree(resources)
    bin_dir = resources / "bin"
    adapter_dir = resources / "adapters"
    bin_dir.mkdir(parents=True)
    adapter_dir.mkdir()

    with tempfile.TemporaryDirectory(
        prefix="factortester-runtime-build-"
    ) as raw:
        root = Path(raw)
        environment = root / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / "bin" / "python"
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                f"pyinstaller=={PYINSTALLER_VERSION}",
                str(repo / "tools" / "cli"),
                str(repo / "tools" / "cli" / "agent-harness"),
            ],
            check=True,
        )
        bootstrap = root / "factortester_runtime.py"
        bootstrap.write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "entry = Path(sys.argv[0]).name\n"
            "if entry == 'cli-anything-factortester-research':\n"
            "    from cli_anything.factortester_research.factortester_research_cli import cli\n"
            "else:\n"
            "    from tools.cli.app import cli\n"
            "cli()\n",
            encoding="utf-8",
        )
        subprocess.run(
            [
                str(environment / "bin" / "pyinstaller"),
                "--clean",
                "--noconfirm",
                "--onefile",
                "--name",
                "factortester",
                "--collect-all",
                "cli_anything.factortester_research",
                "--distpath",
                str(root / "dist"),
                "--workpath",
                str(root / "work"),
                "--specpath",
                str(root / "spec"),
                str(bootstrap),
            ],
            check=True,
        )
        shutil.copy2(root / "dist" / "factortester", bin_dir / "factortester")
        shutil.copy2(
            bin_dir / "factortester",
            bin_dir / "cli-anything-factortester-research",
        )
        subprocess.run(
            [
                sys.executable,
                str(repo / "client-adapters/vibe-trading/build_archive.py"),
                str(adapter_dir / "vibe-trading-adapter.zip"),
            ],
            check=True,
        )

    files = {
        str(path.relative_to(resources)): sha256(path.read_bytes()).hexdigest()
        for path in sorted(resources.rglob("*"))
        if path.is_file()
    }
    receipt = {
        "schema_version": 1,
        "version": version,
        "source_revision": source_revision,
        "files": files,
    }
    receipt_path = resources / "bundle-receipt.json"
    receipt_path.write_text(
        json.dumps(
            receipt,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n",
        encoding="utf-8",
    )
    return receipt_path


def _build_wheel(
    source: Path,
    distribution: str,
    output: Path,
) -> Path:
    with tempfile.TemporaryDirectory(prefix=f"{distribution}-source-") as raw:
        copied = Path(raw) / "source"
        shutil.copytree(
            source,
            copied,
            ignore=shutil.ignore_patterns(
                "agent-harness",
                "build",
                "dist",
                "*.egg-info",
                "__pycache__",
                "*.pyc",
            ),
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-cache-dir",
                "--no-deps",
                "--wheel-dir",
                str(output),
                str(copied),
            ],
            check=True,
        )
    matches = list(output.glob(f"{distribution}-*.whl"))
    if len(matches) != 1:
        raise ValueError(f"expected one {distribution} wheel")
    return matches[0]
