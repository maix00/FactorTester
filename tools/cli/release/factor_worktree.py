"""Profile-isolated Git worktrees over one canonical factor repository."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any
import uuid

from .authoring_runtime import (
    AUTHORING_CONTRACT_ID,
    authoring_status_paths,
    refresh_authoring_metadata,
    run_bundled_pyright,
)
from .factor_worktree_paths import is_adoptable_factor_worktree_target
from .local_profile import LocalProfileStore
from .local_profile_contracts import validate_local_identifier
from .locations import validate_client_root
from .storage import json_hash, read_json, utc_now, write_json


_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_HOOK_ENV = {
    "FACTOR_WORKSPACE_SKIP_AUTOSYNC": "1",
    "GIT_TERMINAL_PROMPT": "0",
}
_GENERATED_BASELINE_SUBJECT = (
    f"chore: refresh {AUTHORING_CONTRACT_ID}"
)


class CanonicalFactorRepoStore:
    def __init__(self, client_root: Path) -> None:
        self.root = validate_client_root(client_root)
        self.path = self.root / "settings" / "factor-workspace.json"

    def register(self, path: Path, *, owner_ref: str) -> dict[str, Any]:
        repo = _repo_root(path)
        owner = _manifest_owner(repo)
        if owner != owner_ref:
            raise ValueError("canonical factor repo owner does not match")
        common = _git_value(repo, "rev-parse", "--git-common-dir")
        value = {
            "schema_version": 1,
            "canonical_repo_ref": _canonical_ref(repo, common),
            "path": str(repo),
            "owner_ref": owner,
            "registered_head": _head(repo),
            "registered_at": utc_now(),
        }
        write_json(self.path, value)
        self.path.chmod(0o600)
        return value

    def load(self) -> dict[str, Any]:
        value = read_json(self.path)
        if not isinstance(value, dict) or set(value) != {
            "schema_version", "canonical_repo_ref", "path", "owner_ref",
            "registered_head", "registered_at",
        }:
            raise ValueError("canonical factor repo is not registered")
        repo = _repo_root(Path(str(value["path"])))
        common = _git_value(repo, "rev-parse", "--git-common-dir")
        if value["canonical_repo_ref"] != _canonical_ref(repo, common):
            raise ValueError("canonical factor repo identity changed")
        if _manifest_owner(repo) != value["owner_ref"]:
            raise ValueError("canonical factor repo owner changed")
        return value


def plan_factor_worktree_binding(
    client_root: Path,
    profile_id: str,
    *,
    branch: str = "",
    worktree_path: Path | None = None,
    source_sync_enabled: bool = False,
) -> dict[str, Any]:
    root = validate_client_root(client_root)
    store = LocalProfileStore(root)
    profile = store.load(profile_id)
    settings = CanonicalFactorRepoStore(root).load()
    repo = Path(str(settings["path"]))
    owner = str(settings["owner_ref"])
    _assert_authorized(profile, owner)
    branch_name = branch or f"agent/{profile_id}"
    _validate_branch(repo, branch_name)
    profile_root = Path(str(profile["workspace_root"])).resolve()
    target = (
        worktree_path.expanduser().resolve()
        if worktree_path is not None
        else profile_root / "factor-worktree"
    )
    _assert_target_path(target, profile_root, repo)
    base = _head(repo)
    status = _git(repo, "status", "--porcelain=v1", "-z")
    status_entries = [item for item in status.split("\0") if item]
    branch_exists = _ref_exists(repo, f"refs/heads/{branch_name}")
    branch_head = (
        _git_value(repo, "rev-parse", f"refs/heads/{branch_name}")
        if branch_exists else ""
    )
    branch_checked_out = any(
        row.get("branch") == f"refs/heads/{branch_name}"
        for row in _worktree_rows(repo)
    )
    branch_is_base_ancestor = bool(
        branch_exists and _is_ancestor(repo, branch_head, base)
    )
    recoverable_branch = branch_is_base_ancestor and not branch_checked_out
    target_exists = target.exists()
    target_is_adoptable = is_adoptable_factor_worktree_target(
        target,
        profile_root=profile_root,
    )
    existing_binding = profile.get("factor_workspace_binding") or {}
    idempotent = bool(
        existing_binding
        and existing_binding.get("canonical_repo_ref")
            == settings["canonical_repo_ref"]
        and existing_binding.get("branch") == branch_name
        and Path(str(existing_binding.get("worktree_path"))).resolve()
            == target
    )
    collisions = []
    if branch_exists and not idempotent and not recoverable_branch:
        collisions.append("branch_exists")
    if target_exists and not idempotent and not target_is_adoptable:
        collisions.append("target_exists")
    existing_paths = {
        Path(item["worktree"]).resolve()
        for item in _worktree_rows(repo)
    }
    if target in existing_paths and not idempotent:
        collisions.append("worktree_path_registered")
    checkout_bytes = _tracked_checkout_bytes(repo, base)
    available = _available_bytes(target.parent)
    body = {
        "schema_version": 1,
        "profile_id": profile_id,
        "canonical_repo_ref": settings["canonical_repo_ref"],
        "canonical_settings_hash": json_hash(settings),
        "owner_ref": owner,
        "base_commit": base,
        "branch": branch_name,
        "worktree_path": str(target),
        "research_root": str(profile_root / "research"),
        "git_common_dir": _absolute_common_dir(repo),
        "canonical_checkout": {
            "branch": _git_value(repo, "branch", "--show-current"),
            "dirty": bool(status_entries),
            "status_count": len(status_entries),
            "status_sha256": sha256(status.encode()).hexdigest(),
            "uncommitted_changes_inherited": False,
        },
        "capacity": {
            "estimated_checkout_bytes": checkout_bytes,
            "available_bytes": available,
            "ok": available >= checkout_bytes * 2,
            "objects_copied": False,
        },
        "checks": {
            "authorized": True,
            "owner_matches": True,
            "base_commit_valid": bool(_COMMIT.fullmatch(base)),
            "target_within_profile_root": True,
            "canonical_checkout_untouched": True,
            "branch_available": (
                not branch_exists or idempotent or recoverable_branch
            ),
            "branch_recovery": (
                (
                    "recoverable_same_base"
                    if branch_head == base
                    else "recoverable_behind_base"
                )
                if recoverable_branch
                else (
                    "manual_repair_required_unique_commits"
                    if branch_exists and not idempotent
                    else "not_needed"
                )
            ),
            "target_available": (
                not target_exists or target_is_adoptable or idempotent
            ),
            "collisions": sorted(set(collisions)),
            "pyright_config_at_base": _tracked_at(repo, base, "pyrightconfig.json"),
            "pyi_at_base": bool(_tracked_glob(repo, base, "*.pyi")),
        },
        "sync_policy": {
            "source_sync_enabled": bool(source_sync_enabled),
            "auto_push": False,
            "auto_merge": False,
        },
        "idempotent": idempotent,
    }
    body["ready"] = (
        not body["checks"]["collisions"]
        and body["capacity"]["ok"]
        and body["checks"]["pyright_config_at_base"]
        and body["checks"]["pyi_at_base"]
    )
    plan = {**body, "plan_hash": json_hash(body)}
    plan["binding_id"] = f"factor-worktree-{plan['plan_hash'][:16]}"
    return plan


def apply_factor_worktree_binding(
    client_root: Path,
    plan: dict[str, Any],
    *,
    checkpoint=None,
) -> dict[str, Any]:
    _validate_plan(plan)
    if not plan.get("ready"):
        raise ValueError("factor worktree plan is not ready")
    root = validate_client_root(client_root)
    store = LocalProfileStore(root)
    profile = store.load(str(plan["profile_id"]))
    settings = CanonicalFactorRepoStore(root).load()
    if json_hash(settings) != plan["canonical_settings_hash"]:
        raise ValueError("canonical factor repo settings changed after plan")
    repo = Path(str(settings["path"]))
    _assert_authorized(profile, str(plan["owner_ref"]))
    _assert_canonical_unchanged(repo, plan)
    target = Path(str(plan["worktree_path"]))
    receipt_path = _receipt_path(
        store.root, str(plan["profile_id"]), str(plan["binding_id"])
    )
    existing = read_json(receipt_path)
    if isinstance(existing, dict):
        _validate_receipt(existing, plan)
        current_binding = profile.get("factor_workspace_binding") or {}
        if current_binding and current_binding.get("binding_id") != (
            plan["binding_id"]
        ):
            raise ValueError("profile points to another factor worktree binding")
        if not current_binding:
            if not _matches_planned_worktree(repo, target, plan):
                raise ValueError(
                    "factor worktree receipt exists but worktree is invalid"
                )
            profile["factor_workspace_binding"] = _binding_from_receipt(
                existing, receipt_path
            )
            store.save(profile)
        verification = verify_factor_worktree_binding(
            root, str(plan["profile_id"])
        )
        if verification["valid"]:
            return existing
        raise ValueError("factor worktree receipt exists but binding is invalid")
    recovered = _matches_planned_worktree(repo, target, plan)
    generated_baseline: dict[str, Any]
    if not recovered:
        branch_exists = _ref_exists(
            repo, f"refs/heads/{plan['branch']}"
        )
        branch_head = (
            _git_value(repo, "rev-parse", f"refs/heads/{plan['branch']}")
            if branch_exists else ""
        )
        checked_out = any(
            row.get("branch") == f"refs/heads/{plan['branch']}"
            for row in _worktree_rows(repo)
        )
        recover_branch = (
            branch_exists
            and _is_ancestor(repo, branch_head, str(plan["base_commit"]))
            and not checked_out
        )
        if branch_exists and not recover_branch:
            raise ValueError(
                "factor worktree branch has unique commits or is checked out; "
                "manual repair is required"
        )
        if target.exists():
            profile_root = Path(str(profile["workspace_root"])).resolve()
            if not is_adoptable_factor_worktree_target(
                target,
                profile_root=profile_root,
            ):
                raise ValueError("factor worktree target collision")
            target.rmdir()
        staging = target.parent / f".{target.name}.staging-{uuid.uuid4().hex}"
        target.parent.mkdir(parents=True, exist_ok=True)
        branch_started_at_base = not branch_exists or recover_branch
        try:
            if recover_branch:
                if branch_head != plan["base_commit"]:
                    _git_checked(
                        repo,
                        "branch",
                        "-f",
                        str(plan["branch"]),
                        str(plan["base_commit"]),
                    )
                _git_checked(
                    repo, "worktree", "add",
                    str(staging), str(plan["branch"]),
                )
            else:
                _git_checked(
                    repo, "worktree", "add", "-b", str(plan["branch"]),
                    str(staging), str(plan["base_commit"]),
                )
            _write_worktree_manifest(staging, plan)
            generated_baseline = _prepare_generated_baseline(staging, plan)
            _checkpoint(checkpoint, "before_publish")
            _git_checked(repo, "worktree", "move", str(staging), str(target))
        except Exception:
            if _is_worktree(repo, staging):
                _git_result(
                    repo, "worktree", "remove", "--force", str(staging)
                )
            if (
                branch_started_at_base
                and _ref_exists(repo, f"refs/heads/{plan['branch']}")
                and _generated_commit_is_safe_to_discard(repo, plan)
            ):
                _git_checked(
                    repo, "branch", "-f", str(plan["branch"]),
                    str(plan["base_commit"]),
                )
            raise
    else:
        generated_baseline = _prepare_generated_baseline(target, plan)
    research_root = Path(str(plan["research_root"]))
    research_root.mkdir(parents=True, exist_ok=True)
    _configure_safe_hooks(repo, target, research_root)
    _write_worktree_manifest(target, plan)
    if _head(target) != generated_baseline["baseline_commit"]:
        raise ValueError("generated authoring baseline changed during publication")
    _checkpoint(checkpoint, "before_receipt")
    receipt = _build_receipt(plan, generated_baseline)
    write_json(receipt_path, receipt)
    receipt_path.chmod(0o600)
    _checkpoint(checkpoint, "before_profile")
    profile["factor_workspace_binding"] = _binding_from_receipt(
        receipt, receipt_path
    )
    store.save(profile)
    return receipt


def verify_factor_worktree_binding(
    client_root: Path,
    profile_id: str,
    *,
    run_pyright: bool = False,
) -> dict[str, Any]:
    root = validate_client_root(client_root)
    profile = LocalProfileStore(root).load(profile_id)
    binding = profile.get("factor_workspace_binding") or {}
    if not binding:
        return {"schema_version": 1, "profile_id": profile_id, "valid": False,
                "checks": {"binding_present": False}}
    settings = CanonicalFactorRepoStore(root).load()
    repo = Path(str(settings["path"]))
    target = Path(str(binding["worktree_path"]))
    checks = {
        "binding_present": True,
        "canonical_repo_matches": (
            binding["canonical_repo_ref"] == settings["canonical_repo_ref"]
        ),
        "owner_preserved": binding["owner_ref"] == settings["owner_ref"],
        "worktree_registered": _is_worktree(repo, target),
        "branch_matches": _git_value(target, "branch", "--show-current")
            == binding["branch"],
        "head_matches_or_advances": _is_ancestor(
            repo, str(binding["base_commit"]), _git_value(target, "rev-parse", "HEAD")
        ),
        "shared_object_store": _absolute_common_dir(target)
            == binding["git_common_dir"],
        "safe_hooks": _git_value(
            target, "config", "--worktree", "--get", "core.hooksPath"
        ) == str(target / ".factortester" / "hooks-disabled"),
        "safe_excludes": _git_value(
            target, "config", "--worktree", "--get", "core.excludesFile"
        ) == str(Path(str(binding["research_root"])) / "factor-worktree.gitignore"),
        "pyright_config": (target / "pyrightconfig.json").is_file(),
        "pyi_present": any(target.rglob("*.pyi")) if target.is_dir() else False,
        "research_root_separate": not _is_within(
            Path(str(binding["research_root"])), target
        ),
        "auto_push_disabled": binding["sync_policy"]["auto_push"] is False,
        "auto_merge_disabled": binding["sync_policy"]["auto_merge"] is False,
    }
    if run_pyright and all(
        checks[key] for key in ("worktree_registered", "pyright_config", "pyi_present")
    ):
        checks["pyright_zero_errors"] = _pyright_ok(target)
    return {
        "schema_version": 1,
        "profile_id": profile_id,
        "valid": all(checks.values()),
        "checks": checks,
    }


def repair_factor_worktree_binding(
    client_root: Path,
    profile_id: str,
    *,
    run_pyright: bool = True,
    refresh_manifest: bool = True,
) -> dict[str, Any]:
    root = validate_client_root(client_root)
    profile = LocalProfileStore(root).load(profile_id)
    binding = profile.get("factor_workspace_binding") or {}
    if not binding:
        raise ValueError("factor worktree binding is missing")
    settings = CanonicalFactorRepoStore(root).load()
    repo = Path(str(settings["path"]))
    target = Path(str(binding["worktree_path"]))
    if (
        binding["canonical_repo_ref"] != settings["canonical_repo_ref"]
        or binding["owner_ref"] != settings["owner_ref"]
        or not _is_worktree(repo, target)
        or _git_value(target, "branch", "--show-current") != binding["branch"]
        or not _is_ancestor(repo, binding["base_commit"], _head(target))
    ):
        raise ValueError("factor worktree identity drift cannot be auto-repaired")
    research_root = Path(str(binding["research_root"]))
    research_root.mkdir(parents=True, exist_ok=True)
    _configure_safe_hooks(repo, target, research_root)
    if refresh_manifest:
        _write_binding_manifest(target, binding)
    return verify_factor_worktree_binding(
        root, profile_id, run_pyright=run_pyright
    )


def rollback_factor_worktree_binding(
    client_root: Path,
    profile_id: str,
    binding_id: str,
) -> dict[str, Any]:
    root = validate_client_root(client_root)
    store = LocalProfileStore(root)
    profile = store.load(profile_id)
    binding = profile.get("factor_workspace_binding") or {}
    receipt_path = _receipt_path(store.root, profile_id, binding_id)
    if not binding:
        previous = read_json(receipt_path)
        if isinstance(previous, dict) and previous.get("status") == "rolled_back":
            return {
                **previous,
                "receipt_ref": receipt_path.resolve().as_uri(),
            }
    if binding.get("binding_id") != binding_id:
        raise ValueError("factor worktree binding no longer matches rollback")
    settings = CanonicalFactorRepoStore(root).load()
    repo = Path(str(settings["path"]))
    target = Path(str(binding["worktree_path"]))
    if _git_value(target, "status", "--porcelain"):
        raise ValueError("factor worktree has uncommitted changes; rollback refused")
    _git_checked(repo, "worktree", "remove", str(target))
    profile["factor_workspace_binding"] = {}
    store.save(profile)
    receipt = read_json(receipt_path) or {}
    receipt.update({
        "action": "unbind",
        "status": "rolled_back",
        "profile_id": profile_id,
        "branch_retained": True,
        "commits_retained": True,
    })
    receipt.pop("receipt_hash", None)
    receipt["receipt_hash"] = json_hash(receipt)
    write_json(receipt_path, receipt)
    receipt_path.chmod(0o600)
    return {**receipt, "receipt_ref": receipt_path.resolve().as_uri()}


def _assert_authorized(profile: dict[str, Any], owner: str) -> None:
    session = profile.get("session_binding") or {}
    principal = str(session.get("principal_ref") or "")
    if not principal:
        raise ValueError("profile has no authenticated principal binding")
    allowed = principal == owner or any(
        source.get("owner_ref") == owner
        and source.get("principal_ref") == principal
        for source in profile.get("initialization_sources") or []
    )
    if not allowed:
        raise ValueError("profile is not authorized for canonical factor owner")


def _assert_target_path(target: Path, profile_root: Path, repo: Path) -> None:
    if not _is_within(target, profile_root):
        raise ValueError("factor worktree must be inside the profile workspace root")
    if _is_within(target, repo) or _is_within(repo, target):
        raise ValueError("factor worktree must be separate from canonical checkout")


def _assert_canonical_unchanged(repo: Path, plan: dict[str, Any]) -> None:
    if _head(repo) != plan["base_commit"]:
        raise ValueError("canonical factor repo HEAD changed after plan")
    status = _git(repo, "status", "--porcelain=v1", "-z")
    if sha256(status.encode()).hexdigest() != (
        plan["canonical_checkout"]["status_sha256"]
    ):
        raise ValueError("canonical checkout changed after plan")
    if _manifest_owner(repo) != plan["owner_ref"]:
        raise ValueError("canonical factor repo owner changed after plan")


def _configure_safe_hooks(
    repo: Path,
    worktree: Path,
    research_root: Path,
) -> None:
    hooks = worktree / ".factortester" / "hooks-disabled"
    hooks.mkdir(parents=True, exist_ok=True)
    excludes = research_root / "factor-worktree.gitignore"
    excludes.write_text(".factor_workspace/manifest.json\n.factortester/\n")
    _git_checked(repo, "config", "extensions.worktreeConfig", "true")
    _git_checked(
        worktree, "config", "--worktree", "core.hooksPath", str(hooks)
    )
    _git_checked(
        worktree,
        "config",
        "--worktree",
        "core.excludesFile",
        str(excludes),
    )


def _write_worktree_manifest(worktree: Path, plan: dict[str, Any]) -> None:
    binding = {
        "canonical_repo_ref": plan["canonical_repo_ref"],
        "base_commit": plan["base_commit"],
        "branch": plan["branch"],
        "worktree_path": plan["worktree_path"],
        "owner_ref": plan["owner_ref"],
        "sync_policy": plan["sync_policy"],
    }
    _write_binding_manifest(worktree, binding)


def _write_binding_manifest(worktree: Path, binding: dict[str, Any]) -> None:
    path = worktree / ".factor_workspace" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "schema_version": 2,
        "username": binding["owner_ref"],
        "workspace_root": str(worktree),
        "custom_factor_dir": str(worktree / "custom_factors"),
        "public_factor_dir": str(worktree / "public_factors"),
        "git": {
            "git_enabled": True,
            "git_repo_root": str(worktree),
            "workspace_root": str(worktree),
            "git_current_branch": binding["branch"],
            "auto_push": False,
            "auto_merge": False,
        },
        "binding": {
            "canonical_repo_ref": binding["canonical_repo_ref"],
            "base_commit": binding["base_commit"],
        },
    }
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )


def _prepare_generated_baseline(
    worktree: Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
    refresh = refresh_authoring_metadata(worktree)
    changed = list(refresh["changed_paths"])
    created = False
    if changed:
        _git_checked(worktree, "add", "--", *changed)
        date = _git_value(
            worktree,
            "show",
            "-s",
            "--format=%aI",
            str(plan["base_commit"]),
        )
        result = subprocess.run(
            [
                "git",
                "-C",
                str(worktree),
                "-c",
                "user.name=FactorTester Client",
                "-c",
                "user.email=factortester-client@invalid",
                "-c",
                "core.hooksPath=/dev/null",
                "commit",
                "-m",
                _GENERATED_BASELINE_SUBJECT,
            ],
            env={
                **os.environ,
                **_HOOK_ENV,
                "GIT_AUTHOR_DATE": date,
                "GIT_COMMITTER_DATE": date,
            },
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise ValueError(
                "cannot commit generated authoring baseline: "
                + result.stderr.strip()
            )
        created = True
    elif _head(worktree) != plan["base_commit"]:
        if not _generated_baseline_matches(worktree, plan):
            raise ValueError("factor worktree has an unrecognized baseline commit")
        changed = _git(
            worktree,
            "diff",
            "--name-only",
            f"{plan['base_commit']}..HEAD",
        ).splitlines()
    if authoring_status_paths(worktree):
        raise ValueError("generated authoring baseline did not leave a clean worktree")
    pyright = _assert_authoring_ready(worktree)
    return {
        **refresh,
        "changed_paths": changed,
        "base_commit": plan["base_commit"],
        "baseline_commit": _head(worktree),
        "commit_created": created,
        "commit_subject": (
            _GENERATED_BASELINE_SUBJECT if changed else None
        ),
        "pyright": pyright,
    }


def _generated_baseline_matches(
    worktree: Path,
    plan: dict[str, Any],
) -> bool:
    head = _head(worktree)
    if head == plan["base_commit"]:
        return True
    parents = _git_value(worktree, "show", "-s", "--format=%P", head).split()
    subject = _git_value(worktree, "show", "-s", "--format=%s", head)
    changed = set(
        _git(
            worktree,
            "diff",
            "--name-only",
            f"{plan['base_commit']}..{head}",
        ).splitlines()
    )
    return (
        parents == [plan["base_commit"]]
        and subject == _GENERATED_BASELINE_SUBJECT
        and bool(changed)
        and changed <= {
            "pyrightconfig.json",
            "tools/factors/Parameters.pyi",
        }
        and not authoring_status_paths(worktree)
    )


def _generated_commit_is_safe_to_discard(
    repo: Path,
    plan: dict[str, Any],
) -> bool:
    branch_head = _git_value(
        repo, "rev-parse", f"refs/heads/{plan['branch']}"
    )
    if branch_head == plan["base_commit"]:
        return True
    parents = _git_value(
        repo, "show", "-s", "--format=%P", branch_head
    ).split()
    subject = _git_value(
        repo, "show", "-s", "--format=%s", branch_head
    )
    changed = set(
        _git(
            repo,
            "diff",
            "--name-only",
            f"{plan['base_commit']}..{branch_head}",
        ).splitlines()
    )
    return (
        parents == [plan["base_commit"]]
        and subject == _GENERATED_BASELINE_SUBJECT
        and bool(changed)
        and changed <= {
            "pyrightconfig.json",
            "tools/factors/Parameters.pyi",
        }
    )


def _assert_authoring_ready(worktree: Path) -> dict[str, Any]:
    if not (worktree / "pyrightconfig.json").is_file():
        raise ValueError("factor worktree has no pyrightconfig.json")
    if not any(worktree.rglob("*.pyi")):
        raise ValueError("factor worktree has no authoring stubs")
    result = run_bundled_pyright(worktree)
    if result["returncode"] or result["error_count"]:
        raise ValueError("factor worktree Pyright validation failed")
    return result


def _pyright_ok(worktree: Path) -> bool:
    result = run_bundled_pyright(worktree)
    return result["returncode"] == 0 and result["error_count"] == 0


def _build_receipt(
    plan: dict[str, Any],
    generated_baseline: dict[str, Any],
) -> dict[str, Any]:
    body = {
        "schema_version": 1,
        "binding_id": plan["binding_id"],
        "profile_id": plan["profile_id"],
        "canonical_repo_ref": plan["canonical_repo_ref"],
        "base_commit": plan["base_commit"],
        "branch": plan["branch"],
        "worktree_path": plan["worktree_path"],
        "research_root": plan["research_root"],
        "git_common_dir": plan["git_common_dir"],
        "owner_ref": plan["owner_ref"],
        "sync_policy": plan["sync_policy"],
        "generated_baseline": generated_baseline,
        "plan_hash": plan["plan_hash"],
        "status": "applied",
        "created_at": utc_now(),
    }
    return {**body, "receipt_hash": json_hash(body)}


def _binding_from_receipt(
    receipt: dict[str, Any],
    receipt_path: Path,
) -> dict[str, Any]:
    fields = (
        "binding_id", "canonical_repo_ref", "base_commit", "branch",
        "worktree_path", "research_root", "git_common_dir", "owner_ref",
        "sync_policy", "receipt_hash",
    )
    return {
        **{field: receipt[field] for field in fields},
        "receipt_ref": receipt_path.resolve().as_uri(),
    }


def _matches_planned_worktree(
    repo: Path,
    target: Path,
    plan: dict[str, Any],
) -> bool:
    return (
        target.is_dir()
        and _is_worktree(repo, target)
        and _git_value(target, "branch", "--show-current") == plan["branch"]
        and (
            _head(target) == plan["base_commit"]
            or _generated_baseline_matches(target, plan)
        )
        and _absolute_common_dir(target) == plan["git_common_dir"]
    )


def _validate_plan(plan: dict[str, Any]) -> None:
    expected = str(plan.get("plan_hash") or "")
    binding_id = str(plan.get("binding_id") or "")
    body = {
        key: value for key, value in plan.items()
        if key not in {"plan_hash", "binding_id"}
    }
    if expected != json_hash(body):
        raise ValueError("factor worktree plan hash mismatch")
    if binding_id != f"factor-worktree-{expected[:16]}":
        raise ValueError("factor worktree binding identity mismatch")
    validate_local_identifier(binding_id, "binding_id")


def _validate_receipt(
    receipt: dict[str, Any],
    plan: dict[str, Any],
) -> None:
    declared = str(receipt.get("receipt_hash") or "")
    body = dict(receipt)
    body.pop("receipt_hash", None)
    if declared != json_hash(body):
        raise ValueError("factor worktree receipt hash mismatch")
    if (
        receipt.get("status") != "applied"
        or receipt.get("binding_id") != plan["binding_id"]
        or receipt.get("plan_hash") != plan["plan_hash"]
    ):
        raise ValueError("factor worktree receipt does not match plan")


def _repo_root(path: Path) -> Path:
    root = path.expanduser().resolve()
    if not root.is_dir():
        raise ValueError("canonical factor repo not found")
    observed = _git_value(root, "rev-parse", "--show-toplevel")
    if not observed or Path(observed).resolve() != root:
        raise ValueError("canonical factor repo must be the Git toplevel")
    return root


def _manifest_owner(repo: Path) -> str:
    path = repo / ".factor_workspace" / "manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        owner = str(value.get("username") or "").strip()
    except (OSError, ValueError):
        owner = ""
    if not owner:
        raise ValueError("canonical factor repo owner manifest is missing")
    return owner


def _canonical_ref(repo: Path, common: str) -> str:
    payload = f"{repo}\0{Path(repo, common).resolve()}".encode()
    return f"local-factor-git://{sha256(payload).hexdigest()}"


def _absolute_common_dir(repo: Path) -> str:
    value = _git_value(repo, "rev-parse", "--git-common-dir")
    path = Path(value)
    return str((repo / path).resolve() if not path.is_absolute() else path.resolve())


def _head(repo: Path) -> str:
    value = _git_value(repo, "rev-parse", "HEAD")
    if not _COMMIT.fullmatch(value):
        raise ValueError("factor repo HEAD is invalid")
    return value


def _validate_branch(repo: Path, branch: str) -> None:
    result = _git_result(repo, "check-ref-format", "--branch", branch)
    if result.returncode:
        raise ValueError("factor worktree branch name is invalid")


def _ref_exists(repo: Path, reference: str) -> bool:
    return _git_result(repo, "show-ref", "--verify", "--quiet", reference).returncode == 0


def _tracked_at(repo: Path, commit: str, path: str) -> bool:
    return _git_result(repo, "cat-file", "-e", f"{commit}:{path}").returncode == 0


def _tracked_glob(repo: Path, commit: str, pattern: str) -> list[str]:
    return [
        item for item in _git(repo, "ls-tree", "-r", "--name-only", commit).splitlines()
        if Path(item).match(pattern)
    ]


def _tracked_checkout_bytes(repo: Path, commit: str) -> int:
    total = 0
    for line in _git(repo, "ls-tree", "-lr", commit).splitlines():
        try:
            metadata, _ = line.split("\t", 1)
            size = metadata.rsplit(" ", 1)[1]
            if size != "-":
                total += int(size)
        except (ValueError, IndexError):
            continue
    return total


def _worktree_rows(repo: Path) -> list[dict[str, str]]:
    rows = []
    current: dict[str, str] = {}
    for line in _git(repo, "worktree", "list", "--porcelain").splitlines():
        if not line:
            if current:
                rows.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        rows.append(current)
    return rows


def _is_worktree(repo: Path, path: Path) -> bool:
    target = path.resolve()
    return any(Path(row["worktree"]).resolve() == target for row in _worktree_rows(repo))


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    if not _COMMIT.fullmatch(descendant):
        return False
    return _git_result(repo, "merge-base", "--is-ancestor", ancestor, descendant).returncode == 0


def _available_bytes(path: Path) -> int:
    current = path
    while not current.exists():
        current = current.parent
    return shutil.disk_usage(current).free


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _git(repo: Path, *arguments: str) -> str:
    result = _git_result(repo, *arguments)
    if result.returncode:
        raise ValueError(
            f"git {' '.join(arguments)} failed: {result.stderr.strip()}"
        )
    return result.stdout


def _git_value(repo: Path, *arguments: str) -> str:
    result = _git_result(repo, *arguments)
    return result.stdout.strip() if result.returncode == 0 else ""


def _git_checked(repo: Path, *arguments: str) -> None:
    _git(repo, *arguments)


def _git_result(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        env={**os.environ, **_HOOK_ENV},
        capture_output=True,
        text=True,
        check=False,
    )


def _checkpoint(callback, name: str) -> None:
    if callback is not None:
        callback(name)


def _receipt_path(root: Path, profile_id: str, binding_id: str) -> Path:
    validate_local_identifier(profile_id, "profile_id")
    validate_local_identifier(binding_id, "binding_id")
    return root / "factor-worktree-receipts" / profile_id / f"{binding_id}.json"
