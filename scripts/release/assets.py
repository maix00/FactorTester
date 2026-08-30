"""Build immutable client release assets."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from scripts.release.package_layout import validate_client_package_layout

DEPENDENCIES = (
    "click==8.4.1",
    "markdown-it-py==4.2.0",
    "mdurl==0.1.2",
    "orjson==3.11.9",
    "plotext==5.3.2",
    "pygments==2.20.0",
    "rich==15.0.0",
)
PYINSTALLER_VERSION = "6.21.0"
PYRIGHT_VERSION = "1.1.411"
RUNTIME_CACHE_SCHEMA = 8
_SOURCE_REVISION = re.compile(r"^[0-9a-f]{40}$")
_MACHO_PREFIXES = {
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
}


def _create_runtime_environment(environment: Path) -> None:
    """Create the build venv from source Python or a real host interpreter."""
    if not getattr(sys, "frozen", False):
        import venv

        venv.EnvBuilder(with_pip=True).create(environment)
        return

    interpreter = os.environ.get("FTCLIENT_RELEASE_PYTHON") or shutil.which(
        "python3"
    )
    if not interpreter:
        raise RuntimeError(
            "A host python3 interpreter is required to publish a client "
            "release from the bundled Manager CLI"
        )
    subprocess.run(
        [interpreter, "-m", "venv", str(environment)],
        check=True,
    )


def runtime_input_digest(
    repo: Path,
    *,
    client_sources_root: Path | None = None,
    client_adapters_root: Path | None = None,
) -> str:
    """Hash only inputs which can change the frozen CLI runtime."""
    digest = sha256()
    digest.update(f"schema={RUNTIME_CACHE_SCHEMA}\n".encode())
    digest.update(f"python={sys.version_info[:3]}\n".encode())
    digest.update(f"pyinstaller={PYINSTALLER_VERSION}\n".encode())
    digest.update(f"pyright={PYRIGHT_VERSION}\n".encode())
    digest.update(("\n".join(DEPENDENCIES) + "\n").encode())
    roots = (
        repo / "tools/cli/pyproject.toml",
        repo / "tools/cli",
        repo / "tools/cli/agent-harness/pyproject.toml",
        repo / "tools/cli/agent-harness/cli_anything",
    )
    labeled_roots = [(root, "repo") for root in roots]
    if client_sources_root is not None:
        labeled_roots.append((client_sources_root, "client-sources"))
    if client_adapters_root is not None:
        labeled_roots.append((client_adapters_root, "client-adapters"))
    for root, label in labeled_roots:
        root = Path(root).expanduser().resolve()
        paths = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in paths:
            if not path.is_file() or any(
                part in {
                    "__pycache__", "build", "dist", ".pytest_cache",
                    "tests", "docs",
                }
                or part.endswith(".egg-info")
                or part.startswith(".git")
                for part in path.parts
            ):
                continue
            if label == "repo":
                relative = path.relative_to(repo.resolve()).as_posix()
            else:
                relative = (
                    Path("external") / label / path.relative_to(root)
                ).as_posix()
            digest.update(relative.encode() + b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


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
        shutil.copytree(app, root / app.name, symlinks=True)
        (root / "Applications").symlink_to("/Applications")
        subprocess.run(
            [
                "hdiutil",
                "create",
                "-volname",
                "FTClient",
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
    cache_dir: Path | None = None,
    client_sources_root: Path | None = None,
    client_adapters_root: Path | None = None,
) -> Path:
    """Embed the provider-neutral CLI runtime and optional client assets."""
    if not _SOURCE_REVISION.fullmatch(source_revision):
        raise ValueError("runtime source revision must be a full 40-character Git revision")
    validate_client_package_layout(repo)
    resources = app / "Contents" / "Resources" / "FactorTester"
    if resources.exists():
        shutil.rmtree(resources)
    cache_key = runtime_input_digest(
        repo,
        client_sources_root=client_sources_root,
        client_adapters_root=client_adapters_root,
    )
    cached = cache_dir / cache_key if cache_dir is not None else None
    if cached is not None and _valid_runtime_cache(
        cached,
        cache_key,
        expect_sources=client_sources_root is not None,
        expect_adapters=client_adapters_root is not None,
    ):
        shutil.copytree(cached, resources)
        (resources / ".runtime-cache.json").unlink()
        return _write_runtime_receipt(
            resources, version=version, source_revision=source_revision,
            cache_key=cache_key,
        )
    if cached is not None and cached.exists():
        quarantine = cached.with_name(f".{cached.name}.corrupt-{uuid4().hex}")
        try:
            cached.rename(quarantine)
            shutil.rmtree(quarantine)
        except FileNotFoundError:
            pass

    bin_dir = resources / "bin"
    bin_dir.mkdir(parents=True)
    registered_skill = (
        resources / "skills/factortester-research-skill/SKILL.md"
    )
    registered_skill.parent.mkdir(parents=True)
    shutil.copy2(
        repo / "skills/cli-anything-factortester-research/SKILL.md",
        registered_skill,
    )
    if client_sources_root is not None:
        shutil.copytree(
            client_sources_root,
            resources / "sources",
            ignore=shutil.ignore_patterns(
                "__pycache__",
                "*.pyc",
                "*.pyo",
                ".DS_Store",
                "._*",
            ),
        )

    with tempfile.TemporaryDirectory(
        prefix="factortester-runtime-build-"
    ) as raw:
        root = Path(raw)
        environment = root / "venv"
        _create_runtime_environment(environment)
        python = environment / "bin" / "python"
        # Install the two build tools first, then install the source packages
        # without dependency resolution.  The explicit runtime dependency
        # list is the reproducibility boundary; allowing setuptools to resolve
        # broad ``>=`` ranges here makes two releases from the same checkout
        # contain different Python code.
        subprocess.run(
            [
                str(python), "-m", "pip", "install",
                "--disable-pip-version-check",
                f"pyinstaller=={PYINSTALLER_VERSION}",
                f"pyright[nodejs]=={PYRIGHT_VERSION}",
            ],
            check=True,
        )
        subprocess.run(
            [
                str(python), "-m", "pip", "install", "--no-deps",
                "--disable-pip-version-check",
                str(repo / "tools" / "cli"),
                str(repo / "tools" / "cli" / "agent-harness"),
            ],
            check=True,
        )
        subprocess.run(
            [
                str(python), "-m", "pip", "install",
                "--disable-pip-version-check", *DEPENDENCIES,
            ],
            check=True,
        )
        subprocess.run(
            [str(python), "-m", "pip", "check"],
            check=True,
        )
        node_binary = _nodejs_wheel_binary(environment)
        bootstrap = root / "factortester_runtime.py"
        bootstrap.write_text(
            "import os\n"
            "from pathlib import Path\n"
            "import sys\n"
            "entry = os.environ.get(\"FACTORTESTER_ENTRYPOINT\", Path(sys.argv[0]).name)\n"
            "if entry == 'cli-anything-factortester-research':\n"
            "    from cli_anything.factortester_research.factortester_research_cli import cli\n"
            "elif entry == 'factortester-manager':\n"
            "    from tools.cli.manager_app import manager_cli as cli\n"
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
                "--collect-all",
                "pyright",
                "--collect-data",
                "tools.cli.release",
                "--hidden-import",
                "nodejs_wheel",
                "--add-binary",
                f"{node_binary}:nodejs_wheel/bin",
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
        frozen_binary = root / "dist" / "factortester"
        _smoke_test_frozen_runtime(frozen_binary)
        shutil.copy2(frozen_binary, bin_dir / "factortester")
        _build_native_report_renderer(
            repo,
            bin_dir / "factortester-report-renderer",
        )
        research_launcher = bin_dir / "cli-anything-factortester-research"
        research_launcher.write_text(
            "#!/bin/sh\n"
            "set -eu\n"
            "script_dir=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
            "FACTORTESTER_ENTRYPOINT=cli-anything-factortester-research \\\nexec \"$script_dir/factortester\" \"$@\"\n",
            encoding="utf-8",
        )
        research_launcher.chmod(0o755)
        manager_launcher = bin_dir / "factortester-manager"
        manager_launcher.write_text(
            "#!/bin/sh\n"
            "set -eu\n"
            "script_dir=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
            "FACTORTESTER_ENTRYPOINT=factortester-manager \\\nexec \"$script_dir/factortester\" \"$@\"\n",
            encoding="utf-8",
        )
        manager_launcher.chmod(0o755)
        if client_adapters_root is not None:
            adapter_dir = resources / "adapters"
            adapter_dir.mkdir()
            builder = client_adapters_root / "vibe-trading/build_archive.py"
            if not builder.is_file():
                raise ValueError(
                    "external client adapter root is missing "
                    "vibe-trading/build_archive.py"
                )
            subprocess.run(
                [
                    sys.executable,
                    str(builder),
                    str(adapter_dir / "vibe-trading-adapter.zip"),
                ],
                check=True,
            )

    if cached is not None:
        cached.parent.mkdir(parents=True, exist_ok=True)
        staging = cached.with_name(f".{cached.name}.staging-{uuid4().hex}")
        shutil.copytree(resources, staging)
        _write_cache_descriptor(staging, cache_key)
        try:
            staging.rename(cached)
        except FileExistsError:
            shutil.rmtree(staging)
    return _write_runtime_receipt(
        resources, version=version, source_revision=source_revision,
        cache_key=cache_key,
    )


def _smoke_test_frozen_runtime(binary: Path) -> None:
    """Exercise every embedded CLI entrypoint before it enters an app bundle."""
    with binary.open("rb") as handle:
        if handle.read(4) not in _MACHO_PREFIXES:
            # Unit tests use placeholder executables; real PyInstaller output
            # is Mach-O and is always exercised here.
            return
    _run_frozen_help(binary)
    _run_frozen_help(binary, arguments=["client", "profile", "factor-worktree", "--help"])
    research_env = os.environ.copy()
    research_env["FACTORTESTER_ENTRYPOINT"] = (
        "cli-anything-factortester-research"
    )
    _run_frozen_help(binary, env=research_env)
    manager_env = os.environ.copy()
    manager_env["FACTORTESTER_ENTRYPOINT"] = "factortester-manager"
    _run_frozen_help(binary, env=manager_env)


def _run_frozen_help(
    binary: Path,
    *,
    env: dict[str, str] | None = None,
    arguments: list[str] | None = None,
) -> None:
    """Run one frozen entrypoint and retain its diagnostic output on failure."""
    try:
        subprocess.run(
            [str(binary), *(arguments or ["--help"])],
            check=True,
            capture_output=True,
            env=env,
            timeout=60,
        )
    except subprocess.CalledProcessError as exc:
        stdout = (exc.stdout or b"").decode("utf-8", errors="replace")
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace")
        detail = "\n".join(
            part for part in (stdout.strip(), stderr.strip()) if part
        ) or "<no output>"
        raise RuntimeError(
            f"frozen runtime smoke test failed for {binary}:\n{detail}"
        ) from exc


def _build_native_report_renderer(repo: Path, output: Path) -> None:
    """Compile the small macOS PDF backend embedded beside the frozen CLI."""
    if sys.platform != "darwin":
        raise ValueError("the native report renderer can only be built on macOS")
    source = repo / "tools/cli/native/report_renderer.swift"
    if not source.is_file():
        raise ValueError(f"native report renderer source is missing: {source}")
    architecture = platform.machine()
    if architecture not in {"arm64", "x86_64"}:
        raise ValueError(
            f"unsupported report renderer architecture: {architecture}"
        )
    environment = os.environ.copy()
    if not environment.get("DEVELOPER_DIR"):
        for candidate in (
            "/Applications/Xcode.app/Contents/Developer",
            "/Applications/Xcode-beta.app/Contents/Developer",
        ):
            if Path(candidate, "usr/bin/xcodebuild").is_file():
                environment["DEVELOPER_DIR"] = candidate
                break
    subprocess.run(
        [
            "xcrun",
            "swiftc",
            "-O",
            "-target",
            f"{architecture}-apple-macos13.0",
            str(source),
            "-o",
            str(output),
        ],
        env=environment,
        check=True,
        capture_output=True,
    )
    output.chmod(0o755)
    subprocess.run(
        [str(output), "--help"],
        check=True,
        capture_output=True,
        timeout=30,
    )


def _write_runtime_receipt(
    resources: Path,
    *,
    version: str,
    source_revision: str,
    cache_key: str,
) -> Path:
    files = {
        str(path.relative_to(resources)): sha256(path.read_bytes()).hexdigest()
        for path in sorted(resources.rglob("*"))
        if path.is_file() and path.name != "bundle-receipt.json"
    }
    receipt = {
        "schema_version": 1,
        "version": version,
        "source_revision": source_revision,
        "runtime_input_sha256": cache_key,
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


def refresh_runtime_receipt(resources: Path) -> Path:
    """Re-hash an embedded runtime after its Mach-O files are signed."""
    receipt_path = resources / "bundle-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    return _write_runtime_receipt(
        resources,
        version=str(receipt["version"]),
        source_revision=str(receipt["source_revision"]),
        cache_key=str(receipt["runtime_input_sha256"]),
    )


def _runtime_payload_hashes(resources: Path) -> dict[str, str]:
    return {
        str(path.relative_to(resources)): sha256(path.read_bytes()).hexdigest()
        for path in sorted(resources.rglob("*"))
        if path.is_file()
        and path.name not in {"bundle-receipt.json", ".runtime-cache.json"}
    }


def _write_cache_descriptor(resources: Path, cache_key: str) -> None:
    descriptor = resources / ".runtime-cache.json"
    descriptor.write_text(json.dumps({
        "schema_version": RUNTIME_CACHE_SCHEMA,
        "runtime_input_sha256": cache_key,
        "smoke_tested": True,
        "files": _runtime_payload_hashes(resources),
    }, sort_keys=True, separators=(",", ":")) + "\n")
    with descriptor.open("rb") as stream:
        os.fsync(stream.fileno())


def _valid_runtime_cache(
    resources: Path,
    cache_key: str,
    *,
    expect_sources: bool = False,
    expect_adapters: bool = False,
) -> bool:
    required = [
        resources / "bin/factortester",
        resources / "bin/factortester-manager",
        resources / "bin/cli-anything-factortester-research",
        resources / "bin/factortester-report-renderer",
        resources / "skills/factortester-research-skill/SKILL.md",
        resources / ".runtime-cache.json",
    ]
    if expect_adapters:
        required.append(resources / "adapters")
    if expect_sources:
        required.append(resources / "sources")
    if not all(path.is_file() or path.is_dir() for path in required):
        return False
    if expect_sources and not any((resources / "sources").rglob("*")):
        return False
    if expect_adapters and not any(
        path.is_file() for path in (resources / "adapters").rglob("*")
    ):
        return False
    if not expect_sources and (resources / "sources").exists():
        return False
    if not expect_adapters and (resources / "adapters").exists():
        return False
    try:
        value = json.loads((resources / ".runtime-cache.json").read_text())
    except (OSError, ValueError):
        return False
    valid = (
        value.get("schema_version") == RUNTIME_CACHE_SCHEMA
        and value.get("runtime_input_sha256") == cache_key
        and value.get("smoke_tested") is True
        and value.get("files") == _runtime_payload_hashes(resources)
    )
    if not valid:
        return False
    try:
        _smoke_test_frozen_runtime(resources / "bin/factortester")
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    return all(
        path.stat().st_mode & 0o111 != 0
        for path in (
            resources / "bin/factortester-manager",
            resources / "bin/cli-anything-factortester-research",
            resources / "bin/factortester-report-renderer",
        )
    )


def _nodejs_wheel_binary(environment: Path) -> Path:
    matches = list(environment.glob(
        "lib/python*/site-packages/nodejs_wheel/bin/node"
    ))
    if len(matches) != 1 or not matches[0].is_file():
        raise ValueError("pinned nodejs-wheel runtime is missing")
    return matches[0]


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
