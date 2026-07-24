"""Consume a verified update contract and atomically replace FTClient.app."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from urllib.request import urlopen
from uuid import uuid4

from tools.cli.release.update_channel import ValidatedUpdateManifest


def update_application(
    update: ValidatedUpdateManifest,
    *,
    application: Path,
    support_root: Path,
) -> dict:
    support_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="factortester-app-update-", dir=support_root
    ) as raw:
        root = Path(raw)
        dmg = root / "update.dmg"
        with urlopen(update.dmg_url, timeout=60) as response, dmg.open("wb") as out:
            shutil.copyfileobj(response, out)
        if _file_hash(dmg) != update.dmg_sha256:
            raise ValueError("downloaded DMG does not match signed manifest")
        mount = root / "mount"
        mount.mkdir()
        subprocess.run(
            ["hdiutil", "attach", "-readonly", "-nobrowse",
             "-mountpoint", str(mount), str(dmg)],
            check=True, capture_output=True,
        )
        try:
            candidate = mount / "FTClient.app"
            _verify_candidate(candidate, update)
            candidate_requirement, installed_requirement = (
                _require_installed_identity(candidate, application)
            )
            prior = _app_identity(application)
            _quit_application()
            backup = atomic_replace_application(
                candidate, application=application,
                backup_root=support_root / "release-backups",
            )
        finally:
            subprocess.run(
                ["hdiutil", "detach", str(mount)],
                check=True, capture_output=True,
            )
    try:
        subprocess.run(["open", "-n", str(application)], check=True)
        if not _wait_for_process(running=True, timeout=10):
            raise RuntimeError("updated FTClient failed to launch")
    except Exception:
        if backup is not None and backup.exists():
            failed = application.with_name(f".{application.name}.failed-{os.getpid()}")
            application.rename(failed)
            backup.rename(application)
            shutil.rmtree(failed)
            subprocess.run(["open", "-n", str(application)], check=False)
        elif application.exists():
            shutil.rmtree(application)
        raise
    receipt = {
        "schema_version": 1,
        "version": update.version,
        "build": update.build,
        "dmg_sha256": update.dmg_sha256,
        "manifest_hash": update.manifest_hash,
        "application": str(application),
        "backup": str(backup) if backup else None,
        "prior": {
            "version": prior["CFBundleShortVersionString"],
            "build": prior["CFBundleVersion"],
            "designated_requirement": installed_requirement,
        },
    }
    receipt_path = support_root / "app-update-receipt.json"
    temporary = receipt_path.with_suffix(".json.staging")
    temporary.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    temporary.replace(receipt_path)
    return receipt


def atomic_replace_application(
    candidate: Path,
    *,
    application: Path,
    backup_root: Path,
) -> Path | None:
    staging = application.parent / f".{application.name}.staging-{os.getpid()}"
    shutil.copytree(candidate, staging)
    _verify_same_app(candidate, staging)
    backup = None
    try:
        if application.exists():
            backup_root.mkdir(parents=True, exist_ok=True)
            backup = backup_root / (
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                + f"-{uuid4().hex}-{application.name}"
            )
            application.rename(backup)
        staging.rename(application)
        _verify_same_app(candidate, application)
    except Exception:
        if application.exists():
            shutil.rmtree(application)
        if backup is not None and backup.exists():
            backup.rename(application)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return backup


def _verify_candidate(app: Path, update: ValidatedUpdateManifest) -> None:
    if not (app / "Contents/Info.plist").is_file():
        raise ValueError("DMG does not contain FTClient.app")
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(app)],
        check=True, capture_output=True,
    )
    import plistlib
    with (app / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    if info.get("CFBundleIdentifier") != "com.gtht.client":
        raise ValueError("update bundle identifier is invalid")
    if info.get("CFBundleShortVersionString") != update.version:
        raise ValueError("update app version does not match manifest")
    if str(info.get("CFBundleVersion")) != str(update.build):
        raise ValueError("update app build does not match manifest")
    _validate_embedded_runtime(app)


def _verify_same_app(source: Path, target: Path) -> None:
    for relative in (
        Path("Contents/Info.plist"),
        Path("Contents/Resources/FactorTester/bundle-receipt.json"),
        Path("Contents/Resources/FactorTester/bin/factortester"),
    ):
        if not (target / relative).is_file():
            raise ValueError(f"installed app is missing {relative}")
        if _file_hash(source / relative) != _file_hash(target / relative):
            raise ValueError(f"installed app differs at {relative}")
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(target)],
        check=True, capture_output=True,
    )
    source_requirement = _designated_requirement(source)
    target_requirement = _designated_requirement(target)
    if not source_requirement or source_requirement != target_requirement:
        raise ValueError("installed app signing identity changed")


def _validate_embedded_runtime(app: Path) -> None:
    root = app / "Contents/Resources/FactorTester"
    receipt_path = root / "bundle-receipt.json"
    try:
        receipt = json.loads(receipt_path.read_text())
        files = receipt["files"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("embedded runtime receipt is invalid") from exc
    required = {
        "bin/factortester",
        "bin/cli-anything-factortester-research",
        "adapters/vibe-trading-adapter.zip",
    }
    if not required.issubset(files):
        raise ValueError("embedded runtime receipt is incomplete")
    for relative, expected in files.items():
        path = root / relative
        if not path.is_file() or _file_hash(path) != expected:
            raise ValueError(f"embedded runtime hash mismatch: {relative}")
    for relative in ("bin/factortester", "bin/cli-anything-factortester-research"):
        path = root / relative
        if not os.access(path, os.X_OK):
            raise ValueError(f"embedded runtime is not executable: {relative}")


def _app_identity(app: Path) -> dict:
    import plistlib
    with (app / "Contents/Info.plist").open("rb") as stream:
        return plistlib.load(stream)


def _quit_application() -> None:
    subprocess.run(
        ["osascript", "-e", 'tell application "FTClient" to quit'],
        check=False, capture_output=True,
    )
    if _wait_for_process(running=False, timeout=8):
        return
    subprocess.run(["pkill", "-TERM", "-x", "FTClient"], check=False)
    if _wait_for_process(running=False, timeout=4):
        return
    subprocess.run(["pkill", "-KILL", "-x", "FTClient"], check=False)
    if not _wait_for_process(running=False, timeout=2):
        raise RuntimeError("could not stop FTClient before update")


def _wait_for_process(*, running: bool, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        observed = subprocess.run(
            ["pgrep", "-x", "FTClient"], capture_output=True
        ).returncode == 0
        if observed == running:
            return True
        time.sleep(0.2)
    return False


def _designated_requirement(app: Path) -> str:
    result = subprocess.run(
        ["codesign", "-d", "-r-", str(app)],
        check=True, capture_output=True, text=True,
    )
    return ((result.stdout or "") + (result.stderr or "")).strip()


def _require_installed_identity(
    candidate: Path, installed: Path
) -> tuple[str, str]:
    if not installed.is_dir():
        raise ValueError(
            "FTClient.app is not installed; use the DMG for initial install"
        )
    candidate_requirement = _designated_requirement(candidate)
    installed_requirement = _designated_requirement(installed)
    if not candidate_requirement or candidate_requirement != installed_requirement:
        raise ValueError("update signing identity differs from installed app")
    return candidate_requirement, installed_requirement


def _file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
