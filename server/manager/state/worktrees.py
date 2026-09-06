"""Git worktree discovery and externally reconstructed service bundles."""

from __future__ import annotations

import hashlib
import hmac
import os
import subprocess
from pathlib import Path

from server.manager.config import FEAT_PORT, MAIN_PORT
from server.manager.state.models import (
    ExternalProcess as _ExternalProcess,
    ServiceBundle,
    Worktree,
)
from server.manager.state.processes import job_daemon_socket_path
from server.manager.system import extract_issue_number as _extract_issue_number, safe_name


class WorktreeStateMixin:
    """Own executable worktree identity without starting or stopping services."""
    @staticmethod
    def _immutable_source() -> bool:
        return str(
            os.environ.get("FACTORTESTER_IMMUTABLE_SOURCE") or ""
        ).strip().lower() in {"1", "true", "yes", "on"}

    def _worktree_entries(self) -> list[dict[str, str]]:
        if self._immutable_source():
            return []
        out = subprocess.check_output(
            ["git", "worktree", "list", "--porcelain"],
            cwd=self.repo,
            text=True,
        )
        entries: list[dict[str, str]] = []
        cur: dict[str, str] = {}
        for line in out.splitlines():
            if not line:
                if cur:
                    entries.append(cur)
                    cur = {}
                continue
            key, _, value = line.partition(" ")
            cur[key] = value
        if cur:
            entries.append(cur)
        return entries

    def cleanup_detached_worktrees(self) -> list[Path]:
        """Remove stale Manager source snapshots without crossing ownership."""
        if self._immutable_source():
            return []
        try:
            entries = self._worktree_entries()
        except (OSError, subprocess.CalledProcessError):
            return []
        managed_source_root = (
            self.repo / ".workspace" / "manager-sources"
        ).resolve()
        removed: list[Path] = []
        for entry in entries:
            # ``git worktree list --porcelain`` includes the bare repository
            # itself as a ``worktree ...`` block with a ``bare`` marker.  It
            # is the shared object database, never a disposable checkout.
            if entry.get("branch") or "bare" in entry:
                continue
            raw_path = entry.get("worktree")
            if not raw_path:
                continue
            worktree_path = Path(raw_path).resolve()
            try:
                worktree_path.relative_to(managed_source_root)
            except ValueError:
                # A shared Git object store can also own deployment releases,
                # issue worktrees, and checkouts managed by other tools.  A
                # Manager only owns its immutable source cache and must not
                # remove an unrelated detached checkout merely because it has
                # no branch.
                continue
            # A Manager launched from an immutable commit checkout is itself
            # a detached worktree.  Removing its live source tree at startup
            # makes later imports and the next restart fail.  Preserve only
            # the active Manager source; stale commit checkouts remain
            # eligible for the normal detached-worktree cleanup below.
            if worktree_path == self.runtime_source_root:
                continue
            bundle = self.processes.get(self.key(worktree_path))
            if bundle and (
                bundle.api.poll() is None or bundle.daemon.poll() is None
            ):
                continue
            if worktree_path.exists():
                subprocess.run(
                    [
                        "git", "worktree", "remove", "--force", "--",
                        str(worktree_path),
                    ],
                    cwd=self.repo,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                removed.append(worktree_path)
        subprocess.run(
            ["git", "worktree", "prune", "--expire", "now"],
            cwd=self.repo,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return removed

    def worktrees(self) -> list[Worktree]:
        try:
            entries = self._worktree_entries()
        except (OSError, subprocess.CalledProcessError):
            if not self._immutable_source():
                raise
            entries = []

        result: list[Worktree] = []
        for entry in entries:
            if "bare" in entry:
                # The bare repository is an object store, not an executable
                # service and must never appear as a detached port-0 target.
                continue
            path = Path(entry.get("worktree", "")).resolve()
            if not path:
                continue
            try:
                path.relative_to(self.repo / ".workspace" / "manager-sources")
            except ValueError:
                pass
            else:
                # Immutable Manager implementation checkouts are control-plane
                # internals, not service instances and never own a port.
                continue
            branch_ref = entry.get("branch", "")
            branch = branch_ref.removeprefix("refs/heads/") if branch_ref else "(detached)"
            head = entry.get("HEAD", "")[:8]

            if branch in {"main", "master"}:
                port = MAIN_PORT
            elif branch == "feat":
                port = FEAT_PORT
            else:
                issue_num = _extract_issue_number(branch)
                if issue_num is not None:
                    port = MAIN_PORT + issue_num
                else:
                    port = 0  # no port — should be cleaned up

            # The declared release owns the fixed service even when another
            # checkout's branch convention would assign it the same port.
            # Otherwise a main Manager can silently launch stale feat writers.
            if path == self.repo and self.fixed_port:
                branch = self.fixed_branch or self.server_role
                port = self.fixed_port
            elif self.fixed_port and port == self.fixed_port:
                port = 0

            result.append(Worktree(
                path=path, branch=branch, head=head,
                label=branch, port=port,
            ))
        if self.fixed_port and not any(
            item.port == self.fixed_port for item in result
        ):
            result.append(Worktree(
                path=self.repo,
                branch=self.fixed_branch or self.server_role,
                head=self._revision_for_path()[:8],
                label=self.fixed_branch or self.server_role,
                port=self.fixed_port,
            ))
        return sorted(result, key=lambda wt: (
            -1 if wt.port == 0 else wt.port, wt.label
        ))  # no-port worktrees at bottom

    def validate_manager_source(
        self, source_root: str, source_revision: str,
    ) -> Path:
        path = Path(source_root).expanduser().resolve()
        matches = [item for item in self.worktrees() if item.path == path]
        if len(matches) != 1:
            raise ValueError("Manager source must be one registered Git worktree")
        revision = str(source_revision or "").strip()
        actual = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=path, text=True,
        ).strip()
        if revision != actual:
            raise ValueError("Manager source revision does not match worktree HEAD")
        status = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=path, text=True,
        )
        if status.strip():
            raise ValueError("Manager source worktree has uncommitted changes")
        entrypoint = path / "server/manager/app.py"
        if not entrypoint.is_file():
            raise ValueError("Manager source worktree lacks the Manager entrypoint")
        return path

    def key(self, path: Path) -> str:
        return str(path.resolve())

    @staticmethod
    def _process_listing() -> list[tuple[int, str]]:
        try:
            output = subprocess.check_output(
                ["ps", "-axo", "pid=,command="],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError):
            return []
        processes: list[tuple[int, str]] = []
        for line in output.splitlines():
            raw_pid, _, command = line.strip().partition(" ")
            try:
                pid = int(raw_pid)
            except ValueError:
                continue
            if command:
                processes.append((pid, command.strip()))
        return processes

    @staticmethod
    def _process_cwd(pid: int) -> Path | None:
        try:
            output = subprocess.check_output(
                ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        for line in output.splitlines():
            if line.startswith("n"):
                return Path(line[1:]).resolve()
        return None

    def _discover_bundle(self, path: Path, port: int) -> ServiceBundle | None:
        """Find a service that survived a Manager restart.

        The Manager starts services in new process groups, so the children can
        outlive the control process.  Matching both command arguments and cwd
        prevents a reused PID or an unrelated service on the same machine from
        being adopted.
        """
        path = path.resolve()
        deployment_id = f"{safe_name(path.name)}-{port}"
        socket_path = job_daemon_socket_path(path, deployment_id)
        api_pid: int | None = None
        daemon_pid: int | None = None
        for pid, command in self._process_listing():
            is_api_candidate = (
                "start_server.py" in command and f"--port {port}" in command
            )
            is_daemon_candidate = (
                "scripts/research_job_daemon.py" in command
                and f"--deployment-id {deployment_id}" in command
                and f"--socket {socket_path}" in command
            )
            if not is_api_candidate and not is_daemon_candidate:
                continue
            cwd = self._process_cwd(pid)
            same_worktree = cwd is not None and cwd.resolve() == path
            if api_pid is None and is_api_candidate and same_worktree:
                api_pid = pid
            if daemon_pid is None and is_daemon_candidate and same_worktree:
                daemon_pid = pid
            if api_pid is not None and daemon_pid is not None:
                break
        if api_pid is None or daemon_pid is None:
            return None
        return ServiceBundle(
            api=_ExternalProcess(api_pid),
            daemon=_ExternalProcess(daemon_pid),
            socket_path=socket_path,
            deployment_id=deployment_id,
        )
    def _bundle_for_path(self, path: Path) -> ServiceBundle | None:
        key = self.key(path)
        bundle = self.processes.get(key)
        if bundle is not None:
            return bundle
        try:
            worktree = next(
                (item for item in self.worktrees() if item.path == Path(path).resolve()),
                None,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        if (
            worktree is None
            or worktree.port == 0
            or not self._port_is_in_use(worktree.port)
        ):
            return None
        bundle = self._discover_bundle(worktree.path, worktree.port)
        if bundle is not None:
            self.processes[key] = bundle
        return bundle

    def instance_id(self, worktree: Worktree) -> str:
        digest = hmac.new(
            self.capability_token().encode("ascii"),
            self.key(worktree.path).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:24]
        return f"worktree-{digest}"

    def worktree_for_instance(self, instance_id: str) -> Worktree | None:
        return next(
            (
                item
                for item in self.worktrees()
                if self.instance_id(item) == str(instance_id)
            ),
            None,
        )

    def is_running(self, path: Path) -> bool:
        bundle = self._bundle_for_path(path)
        if not bundle:
            return False
        if bundle.api.poll() is not None:
            return False
        return True

    def daemon_running(self, path: Path) -> bool:
        bundle = self._bundle_for_path(path)
        return bool(bundle and bundle.daemon.poll() is None)

    def vibe_running(self) -> bool:
        return bool(
            self.vibe_process is not None
            and self.vibe_process.poll() is None
        )
