#!/usr/bin/env python3
"""Bounded, content-checked Python dependency snapshots for public images.

The snapshot contains installed Python packages, not application code or the
separately-versioned alpha/Nautilus wheels. Extraction runs in a stopped-image
derived, networkless container; verification and installation run in the
BuildKit dependency stage. A release never changes the running application.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import shlex
import stat
import subprocess
import sys
import sysconfig
import tempfile

FORMAT = 1
MAX_BYTES = 2 * 1024**3
_NATIVE_DISTRIBUTIONS = {"nautilus-trader", "py-alpha-lib"}
_BEGIN = "# BEGIN TRADERESEARCH PYTHON DEPENDENCIES"
_END = "# END TRADERESEARCH PYTHON DEPENDENCIES"
# Only this exact cache wrapper is known to install the same packages as the
# legacy pip command. Future changes to the block must change the fingerprint.
_CANONICAL_INSTALL_SHA256 = "034124947e2a058c278bfecaf164ede9a0404e41020fbe7a424bbe9b107acdf3"
_LEGACY = '''RUN python -m pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" --upgrade pip \\
    && python -m pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" \\
        -r /tmp/requirements-public-linux.txt \\
    && python -c "import celery, plotly; print('execution dependencies ready')"'''
_ARGS = {
    "FACTORTESTER_UID": "1000", "FACTORTESTER_GID": "1000",
    "FACTORTESTER_DEBIAN_MIRROR": "https://deb.debian.org/debian",
    "FACTORTESTER_DEBIAN_SECURITY_MIRROR": "https://deb.debian.org/debian-security",
    "FACTORTESTER_PIP_INDEX_URL": "https://pypi.org/simple",
    "FACTORTESTER_CODEX_VERSION": "0.147.0",
    "FACTORTESTER_CODEX_NPM_REGISTRY": "https://registry.npmjs.org",
}


def dependency_identity(repo: Path, image_platform: str, env: dict[str, str]) -> str:
    """Hash the Python ABI base, entire dependency stage and input files."""
    dockerfile = (repo / "deploy/docker/factortester-public/FactorTester.Dockerfile").read_text()
    prefix = dockerfile.split("\nFROM factortester-public-deps AS ", 1)[0]
    if _BEGIN in prefix and _END in prefix:
        before, rest = prefix.split(_BEGIN, 1)
        middle, after = rest.split(_END, 1)
        block_hash = hashlib.sha256((_BEGIN + middle + _END).encode()).hexdigest()
        marker = ("<python-dependency-install>" if block_hash == _CANONICAL_INSTALL_SHA256
                  else f"<modified-python-dependency-install:{block_hash}>")
        prefix = before + marker + after
    elif _LEGACY in prefix:
        prefix = prefix.replace(_LEGACY, "<python-dependency-install>", 1)
    else:
        raise ValueError("unrecognized Python dependency stage; refusing unsafe cache reuse")
    # Includes and constraints are explicit files under deploy; no path escape.
    deploy = (repo / "deploy").resolve()
    pending = [deploy / "requirements-public-linux.txt"]
    inputs: dict[str, str] = {}
    while pending:
        path = pending.pop().resolve()
        if not path.is_relative_to(deploy):
            raise ValueError("requirements include escapes the deploy directory")
        name = str(path.relative_to(deploy))
        if name in inputs:
            continue
        content = path.read_bytes()
        inputs[name] = hashlib.sha256(content).hexdigest()
        for line in content.decode("utf-8").splitlines():
            tokens = shlex.split(line, comments=True)
            if not tokens:
                continue
            option = tokens[0]
            included = ""
            if option in {"-r", "-c", "--requirement", "--constraint"}:
                if len(tokens) != 2:
                    raise ValueError("invalid nested requirements input")
                included = tokens[1]
            elif option.startswith(("--requirement=", "--constraint=")):
                included = option.split("=", 1)[1]
            elif option.startswith(("-r", "-c")):
                included = option[2:]
            if included:
                if "://" in included:
                    raise ValueError("remote requirements includes are not supported")
                pending.append(path.parent / included)
    config = {"format": FORMAT, "platform": image_platform, "stage": prefix,
              "requirements": inputs, "args": {key: env.get(key, default) for key, default in _ARGS.items()}}
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _distribution_paths(site: Path) -> tuple[set[Path], set[Path], set[str]]:
    """Find native-wheel files/directories and non-native entrypoint scripts."""
    excluded: set[Path] = set()
    executables: set[Path] = set()
    native_roots: set[str] = set()
    non_native_roots: set[str] = set()
    found: set[str] = set()
    native_payload: set[str] = set()
    bin_dir = Path(sys.prefix).resolve() / "bin"
    for dist in importlib.metadata.distributions(path=[str(site)]):
        name = re.sub(r"[-_.]+", "-", str(dist.metadata.get("Name") or "")).lower()
        is_native = name in _NATIVE_DISTRIBUTIONS
        if is_native:
            found.add(name)
            if dist.files is None:
                raise ValueError("native distribution lacks a RECORD inventory")
        for entry in dist.files or []:
            path = Path(dist.locate_file(entry)).resolve()
            if path.is_relative_to(site):
                relative = path.relative_to(site)
                if is_native:
                    excluded.add(path)
                    if not relative.parts[0].endswith(".dist-info"):
                        native_payload.add(name)
                    if len(relative.parts) > 1 and relative.parts[0] != "__pycache__":
                        native_roots.add(relative.parts[0])
                elif len(relative.parts) > 1:
                    non_native_roots.add(relative.parts[0])
            elif not is_native and path.parent == bin_dir and path.is_file():
                executables.add(path)
    if found != _NATIVE_DISTRIBUTIONS:
        raise ValueError("expected installed native distributions are missing")
    if native_payload != _NATIVE_DISTRIBUTIONS:
        raise ValueError("editable or empty native wheel cannot be excluded safely")
    if native_roots & non_native_roots:
        raise ValueError("native and non-native distributions share a package directory")
    return excluded, executables, native_roots


def _copy_hashed(src: Path, dest: Path, remaining: int) -> tuple[int, str]:
    if src.is_symlink() or not src.is_file():
        raise ValueError("Python dependency snapshot contains an unsafe file")
    size = src.stat().st_size
    if size > remaining:
        raise ValueError("Python dependency snapshot exceeds its disk budget")
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with src.open("rb") as source, dest.open("xb") as target:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            target.write(chunk)
    os.chmod(dest, stat.S_IMODE(src.stat().st_mode))
    return size, digest.hexdigest()


def extract(dest: Path, identity: str, image_id: str, max_bytes: int = MAX_BYTES) -> dict:
    """Copy an image's actual installed packages, excluding native wheels."""
    if not re.fullmatch(r"[0-9a-f]{64}", identity) or max_bytes <= 0:
        raise ValueError("invalid Python dependency snapshot identity or budget")
    site = Path(sysconfig.get_path("purelib")).resolve()
    prefix = Path(sys.prefix).resolve()
    if site != Path(sysconfig.get_path("platlib")).resolve() or not site.is_relative_to(prefix):
        raise ValueError("unsupported Python installation layout")
    if any(dest.iterdir()):
        raise ValueError("snapshot destination must be empty")
    excluded, executables, native_roots = _distribution_paths(site)
    entries: list[dict] = []
    total = 0

    def copy(src: Path, relative: Path) -> None:
        nonlocal total
        size, digest = _copy_hashed(src, dest / "tree" / relative, max_bytes - total)
        total += size
        entries.append({"path": relative.as_posix(), "size": size, "sha256": digest,
                        "mode": stat.S_IMODE(src.stat().st_mode)})

    relative_site = site.relative_to(prefix)
    for parent, dirs, files in os.walk(site, followlinks=False):
        parent = Path(parent)
        if parent == site:
            dirs[:] = [name for name in dirs if name not in native_roots]
        if any((parent / item).is_symlink() for item in dirs):
            raise ValueError("symlinked dependency directory is not supported")
        for name in sorted(files):
            file = parent / name
            if file.resolve() not in excluded:
                copy(file, relative_site / file.relative_to(site))
    for file in sorted(executables):
        copy(file, Path("bin") / file.name)
    manifest = {"format": FORMAT, "identity": identity, "source_image_id": image_id,
                "python_tag": sys.implementation.cache_tag,
                "python_soabi": sysconfig.get_config_var("SOABI"),
                "platform": f"{platform.system().lower()}/{platform.machine().lower()}",
                "site": relative_site.as_posix(), "bytes": total,
                "files": sorted(entries, key=lambda item: item["path"])}
    (dest / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")))
    return manifest


def install(snapshot: Path, identity: str, *, prefix: Path = Path(sys.prefix), max_bytes: int = MAX_BYTES) -> None:
    """Verify identity, ABI, paths and bytes before using the snapshot."""
    manifest = json.loads((snapshot / "manifest.json").read_text())
    expected_platform = f"{platform.system().lower()}/{platform.machine().lower()}"
    if (manifest.get("format") != FORMAT or manifest.get("identity") != identity
            or manifest.get("python_tag") != sys.implementation.cache_tag
            or manifest.get("python_soabi") != sysconfig.get_config_var("SOABI")
            or manifest.get("platform") != expected_platform):
        raise ValueError("Python dependency snapshot does not match the build environment")
    expected_site = Path(sysconfig.get_path("purelib")).resolve().relative_to(Path(sys.prefix).resolve())
    if manifest.get("site") != expected_site.as_posix():
        raise ValueError("Python dependency snapshot has an unexpected installation layout")
    total = 0
    seen = set()
    # Hash while staging once; rename after all checks instead of reading the
    # 1+ GiB cache twice. BuildKit discards this layer on any failure.
    with tempfile.TemporaryDirectory(prefix="tr-python-install-") as temp:
        staging = Path(temp)
        for entry in manifest.get("files", []):
            relative = Path(entry["path"])
            if (relative.is_absolute() or ".." in relative.parts or relative in seen
                    or not (relative.is_relative_to(expected_site) or relative.parent == Path("bin"))
                    or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256") or ""))):
                raise ValueError("unsafe or duplicate Python dependency snapshot path")
            seen.add(relative)
            source = snapshot / "tree" / relative
            if (source.is_symlink() or not source.is_file()
                    or not source.resolve().is_relative_to((snapshot / "tree").resolve())
                    or source.stat().st_size != entry["size"]):
                raise ValueError("Python dependency snapshot file is missing or changed")
            size, digest = _copy_hashed(source, staging / relative, max_bytes - total)
            total += size
            if digest != entry["sha256"]:
                raise ValueError("Python dependency snapshot checksum mismatch")
        if total != manifest.get("bytes") or not seen:
            raise ValueError("Python dependency snapshot is incomplete")
        target_site = prefix / expected_site
        if target_site.is_symlink() or not target_site.resolve().is_relative_to(prefix.resolve()):
            raise ValueError("Python dependency target escapes its installation prefix")
        # Replace the base image's installed pip metadata rather than leaving
        # two versions of the same distribution in site-packages.
        if target_site.exists():
            shutil.rmtree(target_site)
        for entry in manifest["files"]:
            relative = Path(entry["path"])
            target = prefix / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.parent.resolve().is_relative_to(prefix.resolve()):
                raise ValueError("Python dependency target escapes its installation prefix")
            os.replace(staging / relative, target)
            os.chmod(target, int(entry["mode"]) & 0o777)


def _run(args: list[str]) -> str:
    return subprocess.run(args, check=True, text=True, capture_output=True, timeout=1800).stdout.strip()


def _image(image: str) -> dict:
    values = json.loads(_run(["docker", "image", "inspect", image]))
    if len(values) != 1 or not isinstance(values[0], dict):
        raise ValueError("unable to identify source image")
    return values[0]


def _image_platform(image: dict) -> str:
    result = f"{image.get('Os', '')}/{image.get('Architecture', '')}"
    if result not in {"linux/amd64", "linux/arm64"}:
        raise ValueError("unsupported Python dependency image platform")
    return result


def _validate_source(image: dict, image_ref: str, source_repo: Path, identity: str, env: dict[str, str]) -> None:
    labels = (image.get("Config") or {}).get("Labels") or {}
    revision = _run(["git", "-C", str(source_repo), "rev-parse", "HEAD"])
    if labels.get("org.opencontainers.image.revision") != revision:
        raise ValueError("running image and source revision differ")
    subprocess.run(["git", "-C", str(source_repo), "diff", "--quiet"], check=True, timeout=60)
    subprocess.run(["git", "-C", str(source_repo), "diff", "--cached", "--quiet"], check=True, timeout=60)
    stamped = labels.get("org.traderesearch.python-deps.identity")
    if stamped and stamped != "unmanaged":
        if stamped != identity:
            raise ValueError("source image dependency identity differs")
        return
    # One-time bootstrap for images predating the identity label. Confirm the
    # exact dependency-stage build arguments from image history; no guessing.
    history = _run(["docker", "image", "history", "--no-trunc", "--format", "{{.CreatedBy}}", image_ref])
    lines = [line for line in history.splitlines()
             if "python -m pip install --no-cache-dir" in line
             and "-r /tmp/requirements-public-linux.txt" in line]
    if len(lines) != 1:
        raise ValueError("legacy dependency build history is missing or ambiguous")
    match = re.search(r"^RUN \|\d+ (.*?) /bin/sh -c ", lines[0])
    if not match:
        raise ValueError("legacy dependency build arguments are unavailable")
    actual = dict(part.split("=", 1) for part in shlex.split(match.group(1)) if "=" in part)
    aliases = {"FACTORTESTER_DEBIAN_MIRROR": "DEBIAN_MIRROR",
               "FACTORTESTER_DEBIAN_SECURITY_MIRROR": "DEBIAN_SECURITY_MIRROR",
               "FACTORTESTER_PIP_INDEX_URL": "PIP_INDEX_URL",
               "FACTORTESTER_CODEX_VERSION": "CODEX_VERSION",
               "FACTORTESTER_CODEX_NPM_REGISTRY": "CODEX_NPM_REGISTRY"}
    for key, default in _ARGS.items():
        if actual.get(aliases.get(key, key)) != env.get(key, default):
            raise ValueError("legacy dependency build arguments differ")


def _snapshot_ok(path: Path, identity: str) -> bool:
    if path.is_symlink() or not path.is_dir():
        return False
    try:
        manifest = path / "manifest.json"
        if manifest.is_symlink() or (path / "tree").is_symlink() or not (path / "tree").is_dir():
            return False
        value = json.loads(manifest.read_text())
        return (value.get("format") == FORMAT and value.get("identity") == identity
                and isinstance(value.get("files"), list) and bool(value["files"])
                and 0 < int(value.get("bytes", 0)) <= MAX_BYTES)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def _root(path: Path) -> Path:
    if path.is_symlink():
        raise ValueError("snapshot root cannot be a symlink")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError("invalid snapshot root")
    state = path.stat()
    if state.st_uid != os.geteuid() or state.st_mode & 0o022:
        raise ValueError("Python snapshot root must not be writable by other users")
    return path.resolve()


def _clean_stale(root: Path, *, keep: str) -> None:
    """Keep the current snapshot and this candidate; remove owned stale ones."""
    current = ""
    pointer = root / "current.json"
    if pointer.exists():
        current = str(json.loads(pointer.read_text()).get("identity") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", current):
            raise ValueError("invalid current Python dependency snapshot pointer")
    for path in root.iterdir():
        if path.name in {current, keep} or path.is_symlink():
            continue
        if re.fullmatch(r"[0-9a-f]{64}", path.name) and _snapshot_ok(path, path.name):
            shutil.rmtree(path)
        elif path.name.startswith(".candidate-") and path.is_dir():
            marker = path / "tr-python-snapshot-owner"
            if marker.is_file() and marker.read_text() == "tr-public-python-snapshot-v1":
                shutil.rmtree(path)


def capture(image_ref: str, identity: str, cache_root: Path, *, require_label: bool = False) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", identity):
        raise ValueError("invalid Python dependency snapshot identity")
    root = _root(cache_root)
    image = _image(image_ref)
    if require_label and ((image.get("Config") or {}).get("Labels") or {}).get(
        "org.traderesearch.python-deps.identity"
    ) != identity:
        raise ValueError("built image does not carry the expected dependency identity")
    target = root / identity
    if target.exists():
        if not _snapshot_ok(target, identity):
            raise ValueError("existing Python snapshot is incomplete or unsafe")
        return target
    _clean_stale(root, keep=identity)
    temporary = Path(tempfile.mkdtemp(prefix=".candidate-", dir=root))
    (temporary / "tr-python-snapshot-owner").write_text("tr-public-python-snapshot-v1")
    payload = temporary / "payload"
    payload.mkdir(mode=0o700)
    try:
        # No network, no writable image filesystem, bounded CPU/RAM/PIDs. This
        # short-lived extraction never starts the Manager or application.
        subprocess.run([
            "docker", "run", "--rm", "--network", "none", "--read-only",
            "--memory", "256m", "--memory-swap", "256m", "--cpus", "0.5", "--pids-limit", "64",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--entrypoint", "/usr/local/bin/python",
            "--mount", f"type=bind,src={Path(__file__).resolve()},dst=/tr-python-deps.py,readonly",
            "--mount", f"type=bind,src={payload},dst=/snapshot",
            str(image["Id"]), "/tr-python-deps.py", "extract", "--dest", "/snapshot",
            "--identity", identity, "--image-id", str(image["Id"]),
        ], check=True, timeout=1800, stdout=subprocess.DEVNULL)
        if not _snapshot_ok(payload, identity):
            raise ValueError("new Python dependency snapshot was not completed")
        os.rename(payload, target)
        return target
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def plan(candidate: Path, source: Path, source_image: str, cache_root: Path, env: dict[str, str]) -> dict:
    """Read-only calculation of candidate identity and maximum disk addition."""
    image = _image(source_image)
    image_platform = _image_platform(image)
    candidate_id = dependency_identity(candidate, image_platform, env)
    source_id = dependency_identity(source, image_platform, env)
    target = cache_root / candidate_id
    if target.exists():
        if not _snapshot_ok(target, candidate_id):
            raise ValueError("Python dependency snapshot is incomplete or unsafe")
        return {"identity": candidate_id, "context": str(target), "reuse_required": True,
                "snapshot_mib": 0}
    return {"identity": candidate_id, "context": "", "reuse_required": candidate_id == source_id,
            "snapshot_mib": MAX_BYTES // 1024**2}


def prepare(candidate: Path, source: Path, source_image: str, cache_root: Path, env: dict[str, str]) -> dict:
    image = _image(source_image)
    decision = plan(candidate, source, source_image, cache_root, env)
    candidate_id = decision["identity"]
    root = _root(cache_root)
    target = root / candidate_id
    if decision["context"]:
        return decision
    if decision["reuse_required"]:
        _validate_source(image, str(image["Id"]), source, candidate_id, env)
        target = capture(str(image["Id"]), candidate_id, root)
        return {"identity": candidate_id, "context": str(target), "reuse_required": True, "snapshot_mib": 0}
    # A dependency change may need index access. The BuildKit pip cache still
    # supplies any unchanged wheels that remain locally available.
    return {"identity": candidate_id, "context": str(candidate / "deploy/docker/factortester-public/wheels"),
            "reuse_required": False, "snapshot_mib": MAX_BYTES // 1024**2}


def promote(cache_root: Path, identity: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", identity):
        raise ValueError("invalid Python dependency snapshot identity")
    root = _root(cache_root)
    target = root / identity
    if not _snapshot_ok(target, identity):
        raise ValueError("cannot promote an incomplete Python dependency snapshot")
    descriptor, temp_name = tempfile.mkstemp(prefix=".current-", dir=root)
    temporary = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump({"format": FORMAT, "identity": identity}, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, root / "current.json")
    finally:
        temporary.unlink(missing_ok=True)
    # Only delete our own complete, content-addressed snapshots. Never remove
    # a user's unknown file, a partial directory, or a symlink.
    for path in root.iterdir():
        if path == target or not re.fullmatch(r"[0-9a-f]{64}", path.name):
            continue
        if _snapshot_ok(path, path.name):
            shutil.rmtree(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    identity_parser = commands.add_parser("identity")
    identity_parser.add_argument("--repo", type=Path, required=True)
    identity_parser.add_argument("--platform", required=True)
    extract_parser = commands.add_parser("extract")
    extract_parser.add_argument("--dest", type=Path, required=True)
    extract_parser.add_argument("--identity", required=True)
    extract_parser.add_argument("--image-id", required=True)
    install_parser = commands.add_parser("install")
    install_parser.add_argument("--snapshot", type=Path, required=True)
    install_parser.add_argument("--identity", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--candidate", type=Path, required=True)
    prepare_parser.add_argument("--source", type=Path, required=True)
    prepare_parser.add_argument("--source-image", required=True)
    prepare_parser.add_argument("--root", type=Path, required=True)
    plan_parser = commands.add_parser("plan")
    plan_parser.add_argument("--candidate", type=Path, required=True)
    plan_parser.add_argument("--source", type=Path, required=True)
    plan_parser.add_argument("--source-image", required=True)
    plan_parser.add_argument("--root", type=Path, required=True)
    capture_parser = commands.add_parser("capture")
    capture_parser.add_argument("--image", required=True)
    capture_parser.add_argument("--identity", required=True)
    capture_parser.add_argument("--root", type=Path, required=True)
    capture_parser.add_argument("--require-label", action="store_true")
    promote_parser = commands.add_parser("promote")
    promote_parser.add_argument("--identity", required=True)
    promote_parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "identity":
        print(dependency_identity(args.repo, args.platform, dict(os.environ)))
    elif args.command == "extract":
        extract(args.dest, args.identity, args.image_id)
    elif args.command == "install":
        install(args.snapshot, args.identity)
    elif args.command == "prepare":
        print(json.dumps(prepare(args.candidate, args.source, args.source_image, args.root, dict(os.environ))))
    elif args.command == "plan":
        print(json.dumps(plan(args.candidate, args.source, args.source_image, args.root, dict(os.environ))))
    elif args.command == "capture":
        print(capture(args.image, args.identity, args.root, require_label=args.require_label))
    else:
        promote(args.root, args.identity)


if __name__ == "__main__":
    main()
