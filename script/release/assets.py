"""Build immutable client release assets."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


DEPENDENCIES = (
    "click==8.4.1",
    "markdown-it-py==4.2.0",
    "mdurl==0.1.2",
    "plotext==5.3.2",
    "pygments==2.20.0",
    "rich==15.0.0",
)


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
