#!/usr/bin/env python3
"""Run a small local UI for starting Flask from multiple git worktrees."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import html
import ipaddress
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urlencode, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.worktree_manager_research import shell_bytes, static_file
from scripts.worktree_manager_gateway import GatewayResponse, ServiceGateway
from scripts.worktree_manager_client_state import ClientStateService
from scripts.worktree_manager_localization import web_localization
from scripts.worktree_manager_preferences import UserPreferenceStore
from scripts.worktree_manager_job_index import ManagerJobIndex
from tools.cli.release.research_reporting.public_research import (
    PublicResearchLibrary,
)
from server.services.client_release_channels import (
    load_beta_sparkle_appcast,
    load_client_release_channel,
)


MAIN_PORT = 8000
FEAT_PORT = 7999
VIBE_TRADING_PORT = 7899
VIBE_TRADING_ROOT = Path(
    os.environ.get(
        "VIBE_TRADING_ROOT",
        "/Users/maxdeux/Documents/Vibe-Trading-Integration",
    )
).expanduser()

# Matches branches named fix/issue-<N>-<slug> or fix/issue-<N>
_ISSUE_BRANCH_RE = re.compile(r'^fix/issue-(\d+)(?:-.*)?$')

_SERVICE_GET_PREFIXES = (
    "/docs",
    "/sqlite-web",
    "/static/css/",
    "/static/js/",
    "/static/vendor/",
    "/static/images/",
    "/custom-factors/api/client/factor-library",
    "/custom-factors/api/client/factor-sets",
    "/api/product-groups",
    "/api/report-references/validate",
    "/api/list_product_names",
    "/api/product_tree",
    "/api/product_fields",
    "/api/contract_tree",
    "/api/get_contracts",
    "/api/profile-research",
    "/api/research-graphs/",
    "/api/research-evidence/",
    "/api/trial-plans/direct/",
    "/api/run-specs/",
    "/api/runs/",
    "/api/client/releases/",
    "/api/testers/modules",
    "/api/backtest/settings/",
    "/api/workspaces",
    "/api/configuration-templates",
)

_PUBLIC_GRAPH_READ_RE = re.compile(
    r"/api/research-graphs/[^/]+/(?:versions|active)$"
)

_SERVICE_WRITE_PATTERNS = {
    "POST": (
        r"/api/product-groups",
        r"/api/get_price_data",
        r"/api/workspaces",
        r"/api/workspaces/[^/]{1,128}/configuration/templates",
        r"/api/workspaces/[^/]{1,128}/configuration/load-template",
        r"/api/runs(?:/preview)?",
    ),
    "PUT": (
        r"/api/workspaces/[^/]{1,128}/configuration",
        r"/api/configuration-templates/[^/]{1,128}",
    ),
    "DELETE": (
        r"/api/configuration-templates/[^/]{1,128}",
    ),
    "PATCH": (
        r"/api/profile-research/[^/]{1,512}/lifecycle",
    ),
}


def _extract_issue_number(branch: str) -> int | None:
    m = _ISSUE_BRANCH_RE.match(branch)
    return int(m.group(1)) if m else None


def _write_owner_only_once(path: Path, value: str) -> None:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    try:
        os.write(fd, value.encode("ascii"))
    finally:
        os.close(fd)


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str
    head: str
    label: str
    port: int  # 0 means no port assigned (should be cleaned up)


@dataclass
class ServiceBundle:
    api: object
    daemon: object
    socket_path: Path
    deployment_id: str


class _ExternalProcess:
    """A process handle reconstructed after the Manager itself restarted."""

    def __init__(self, pid: int) -> None:
        self.pid = int(pid)

    def poll(self) -> int | None:
        try:
            os.kill(self.pid, 0)
        except (OSError, ProcessLookupError):
            return 1
        return None

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self.pid, timeout)
            time.sleep(0.05)
        return 0


class ManagerState:
    def __init__(
        self,
        repo: Path,
        python: str,
        data_root: Path | None = None,
    ) -> None:
        self.repo = repo.resolve()
        self.python = python
        # Manager control state belongs to the source checkout, while
        # user-visible research publications are data and must survive a
        # checkout/release change.  Keep an explicit override for tests and
        # alternate installations; the normal layout is GTHT/FactorTester
        # next to the Codes repository.
        self.data_root = (
            data_root.expanduser().resolve()
            if data_root is not None
            else self.repo.parent / "FactorTester"
        )
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.processes: dict[str, ServiceBundle] = {}
        self.vibe_process: subprocess.Popen | None = None
        self.log_dir = self.repo / ".workspace" / "flask-manager" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.capability_path = self.log_dir.parent / "manager-capability.key"
        self.release_root = self.log_dir.parent / "client-releases"
        self.sessions_path = self.log_dir.parent / "sessions.json"
        self.job_index = ManagerJobIndex(self.log_dir.parent / "job-index.sqlite")
        self._sessions = self._load_sessions()
        self._session_lock = threading.Lock()
        self.public_research = PublicResearchLibrary(
            self.data_root / "public-research",
        )
        self.client_state = ClientStateService()
        self.user_preferences = UserPreferenceStore(
            self.log_dir.parent / "user-preferences",
        )
        self.gateway = ServiceGateway(
            available_ports=self.service_ports,
            capability_token=self.capability_token,
        )

    def login(self, username: str, password: str) -> tuple[str, str, str]:
        principal, role = _authenticate_user(username, password)
        token = secrets.token_urlsafe(32)
        with self._session_lock:
            self._sessions[self._token_hash(token)] = (
                principal, role, time.time() + 12 * 60 * 60,
            )
            self._save_sessions()
        return token, principal, role

    def register(self, alias: str, password: str, organization_id: str = "") -> tuple[str, str, str, str]:
        from tools.data.account_manage import (
            DEFAULT_ORGANIZATION_ID, DEFAULT_ORGANIZATION_NAME,
            ROLE_SUPER_ADMIN, ROLE_USER, accounts_lock, hash_password,
            list_organizations_with_default, load_accounts,
            next_account_username, root_level_id_for_org, save_accounts,
        )
        alias = str(alias or "").strip()
        password = str(password or "")
        if not alias or not password:
            raise ValueError("用户名和密码不能为空")
        if not re.fullmatch(r"[A-Za-z0-9_\u4e00-\u9fff]{1,32}", alias):
            raise ValueError("用户名只能包含字母、数字、下划线或汉字，且不超过32字符")
        if len(password) < 6:
            raise ValueError("密码至少6位")
        organization_id = str(organization_id or DEFAULT_ORGANIZATION_ID).strip()
        org = next((item for item in list_organizations_with_default() if item.get("id") == organization_id), None)
        if not org:
            raise ValueError("机构不存在")
        with accounts_lock:
            accounts = load_accounts()
            full_name = next_account_username(accounts, organization_id, alias)
            salt = secrets.token_hex(16)
            role = ROLE_SUPER_ADMIN if not accounts else ROLE_USER
            accounts.append({
                "username": full_name, "alias": alias, "salt": salt,
                "hash": hash_password(password, salt), "role": role,
                "is_admin": role == ROLE_SUPER_ADMIN,
                "organization_id": organization_id,
                "organization_name": org.get("name") or DEFAULT_ORGANIZATION_NAME,
                "level_id": root_level_id_for_org(organization_id),
                "parent_username": "",
            })
            save_accounts(accounts)
        return full_name, role, alias, organization_id

    def session(self, token: str) -> dict[str, object] | None:
        now = time.time()
        with self._session_lock:
            token_hash = self._token_hash(token)
            session = self._sessions.get(token_hash)
            if session is None:
                return None
            principal, role, expires_at = session
            if expires_at <= now:
                self._sessions.pop(token_hash, None)
                self._save_sessions()
                return None
            return {
                "username": principal,
                "role": role,
                "capabilities": {
                    "manager": role == "super_admin",
                    "research": True,
                },
            }

    def session_principal(self, token: str) -> str | None:
        session = self.session(token)
        return str(session["username"]) if session else None

    def logout(self, token: str) -> None:
        with self._session_lock:
            self._sessions.pop(self._token_hash(token), None)
            self._save_sessions()

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()

    def _load_sessions(self) -> dict[str, tuple[str, str, float]]:
        try:
            payload = json.loads(self.sessions_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            return {}
        now = time.time()
        sessions: dict[str, tuple[str, str, float]] = {}
        for token_hash, value in (payload.get("sessions") or {}).items():
            if not isinstance(value, dict):
                continue
            expires_at = float(value.get("expires_at") or 0)
            if re.fullmatch(r"[0-9a-f]{64}", str(token_hash)) and expires_at > now:
                sessions[str(token_hash)] = (
                    str(value.get("principal") or ""),
                    str(value.get("role") or ""),
                    expires_at,
                )
        return sessions

    def _save_sessions(self) -> None:
        payload = {
            "schema_version": 1,
            "sessions": {
                token_hash: {
                    "principal": value[0],
                    "role": value[1],
                    "expires_at": value[2],
                }
                for token_hash, value in self._sessions.items()
            },
        }
        self.sessions_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=".sessions-", suffix=".json", dir=self.sessions_path.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.sessions_path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def submit_action(self, operation, label: str) -> None:
        """Run one already-authorized operation after its HTTP receipt."""
        def run() -> None:
            try:
                operation()
            except Exception as exc:
                sys.stderr.write(f"[manager] async action {label} failed: {exc}\n")

        threading.Thread(
            target=run,
            name=f"manager-action-{hashlib.sha256(label.encode()).hexdigest()[:8]}",
            daemon=True,
        ).start()

    def capability_token(self) -> str:
        if not self.capability_path.exists():
            _write_owner_only_once(self.capability_path, secrets.token_hex(32))
        self.capability_path.chmod(0o600)
        value = self.capability_path.read_text(encoding="ascii").strip()
        if not value:
            raise RuntimeError("manager capability token is empty")
        return value

    def service_ports(self) -> list[int]:
        return sorted({
            worktree.port for worktree in self.worktrees()
            if worktree.port and port_in_use(worktree.port)
        })

    def preferred_service_port(self) -> int | None:
        running = {
            item.port: item for item in self.worktrees()
            if item.port and port_in_use(item.port)
        }
        if not running:
            return None
        def priority(port: int) -> tuple[int, int]:
            branch = running[port].branch.lower()
            if branch == "main":
                return (0, port)
            if branch == "feat" or branch.startswith("feat/"):
                return (1, port)
            return (2, port)
        return min(running, key=priority)

    def ordered_job_service_ports(self) -> list[int]:
        """Return the preferred service first, tolerating stale Git metadata."""
        preferred = self.preferred_service_port()
        try:
            available = self.service_ports()
        except (OSError, subprocess.CalledProcessError):
            # A temporary/test repository may not have Git worktree metadata;
            # the preferred port is still a valid candidate.
            available = []
        return [
            *([preferred] if preferred is not None else []),
            *[value for value in available if value != preferred],
        ]

    def service_json(
        self, port: int, path: str, principal: str,
    ) -> dict[str, object]:
        return self.gateway.json(
            port=port, path=path, principal=principal,
        )

    def aggregate_jobs(self, principal: str) -> list[dict[str, object]]:
        jobs: list[dict[str, object]] = []
        ports = self.service_ports()
        with ThreadPoolExecutor(max_workers=min(len(ports), 8) or 1) as pool:
            requests = {
                pool.submit(
                    self.service_json, port, "/api/jobs?limit=200", principal,
                ): port
                for port in ports
            }
            for future in as_completed(requests):
                port = requests[future]
                try:
                    values = future.result().get("jobs") or []
                except Exception:
                    continue
                for item in values:
                    if isinstance(item, dict):
                        jobs.append({**item, "port": port})
        self.job_index.upsert(principal, jobs)
        return self.job_index.list(principal)

    def aggregate_public_jobs(
        self, *, cursor: str = "", limit: int = 20,
    ) -> dict[str, object]:
        """Read one public page from the service-wide job repository.

        Public jobs are already indexed in one service database.  Fan-out
        polling every running port made the anonymous page both slow and
        unable to paginate.  Try the preferred live service first and use
        another running service only when the first one is unavailable; the
        returned port is retained only for detail routing.
        """
        bounded_limit = min(20, max(1, int(limit)))
        ordered_ports = self.ordered_job_service_ports()
        for port in ordered_ports:
            query = {"scope": "server", "limit": str(bounded_limit)}
            try:
                value = self.service_json(
                    port,
                    "/api/jobs?" + urlencode(query),
                    "__public_jobs__",
                )
                jobs: list[dict[str, object]] = []
                for item in value.get("jobs") or []:
                    if not isinstance(item, dict):
                        continue
                    raw_port = item.get("port") or item.get("service_port") or port
                    try:
                        job_port = int(raw_port)
                    except (TypeError, ValueError):
                        job_port = port
                    jobs.append({**item, "port": job_port})
                # Anonymous and ordinary accounts receive a fixed public
                # snapshot, not a paginated view of the complete server
                # history.  A service may still return a cursor for its own
                # internal page, so discard it at the Manager boundary.
                jobs = jobs[:20]
                self.job_index.upsert("__public_jobs__", jobs)
                return {
                    "public": True,
                    "jobs": jobs,
                    "page_size": len(jobs),
                    "page": 1,
                    "total": len(jobs),
                    "total_pages": 1,
                    "has_more": False,
                    "next_cursor": None,
                }
            except (ConnectionError, OSError, TypeError, ValueError):
                continue

        cached = [] if cursor else self.job_index.list_all(limit=bounded_limit)
        return {
            "public": True,
            "jobs": cached,
            "page_size": len(cached),
            "page": 1,
            "total": len(cached),
            "total_pages": 1,
            "has_more": False,
            "next_cursor": None,
            "stale": bool(cached),
        }

    def aggregate_server_jobs(
        self, *, principal: str, cursor: str = "", limit: int = 20,
    ) -> dict[str, object]:
        """Read the permissioned server projection for a Manager user.

        Super-admins receive the complete server projection.  If the selected
        service is an old process and cannot accept Manager authentication,
        the cross-principal index remains a bounded, read-only fallback.
        """
        bounded_limit = min(100, max(1, int(limit)))
        ordered_ports = self.ordered_job_service_ports()
        for port in ordered_ports:
            query = {"scope": "server", "limit": str(bounded_limit)}
            if cursor:
                query["cursor"] = cursor
            try:
                value = self.service_json(
                    port,
                    "/api/jobs?" + urlencode(query),
                    principal,
                )
                jobs: list[dict[str, object]] = []
                for item in value.get("jobs") or []:
                    if not isinstance(item, dict):
                        continue
                    raw_port = item.get("port") or item.get("service_port") or port
                    try:
                        job_port = int(raw_port)
                    except (TypeError, ValueError):
                        job_port = port
                    jobs.append({**item, "port": job_port})
                self.job_index.upsert(principal, jobs)
                self.job_index.upsert("__public_jobs__", jobs)
                return {
                    "public": False,
                    "jobs": jobs,
                    "page_size": len(jobs),
                    "page": value.get("page", 1),
                    "total": value.get("total", len(jobs)),
                    "total_pages": value.get("total_pages", 1),
                    "has_more": bool(value.get("has_more")),
                    "next_cursor": value.get("next_cursor"),
                }
            except (ConnectionError, OSError, TypeError, ValueError):
                continue

        cached = [] if cursor else self.job_index.list_all(limit=bounded_limit)
        return {
            "public": False,
            "jobs": cached,
            "page_size": len(cached),
            "page": 1,
            "total": len(cached),
            "total_pages": 1,
            "has_more": False,
            "next_cursor": None,
            "stale": bool(cached),
        }

    def aggregate_account_jobs(
        self,
        *,
        principal: str,
        scope: str,
        username: str = "",
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, object]:
        """Read one account projection from the shared job repository.

        Every FactorTester service points at the same durable job index.  The
        Manager therefore asks one live service for the requested projection,
        rather than polling each port.  Its local index remains a bounded
        fallback for a temporary service restart and for detail routing.
        """
        bounded_limit = min(100, max(1, int(limit)))
        requested_page = max(1, int(page))
        cache_principal = str(username or principal).strip()
        ordered_ports = self.ordered_job_service_ports()
        for port in ordered_ports:
            query: dict[str, str] = {
                "scope": scope,
                "limit": str(bounded_limit),
                "page": str(requested_page),
            }
            if scope == "subordinates" and username:
                query["username"] = username
            try:
                value = self.service_json(
                    port,
                    "/api/jobs?" + urlencode(query),
                    principal,
                )
                jobs: list[dict[str, object]] = []
                for item in value.get("jobs") or []:
                    if not isinstance(item, dict):
                        continue
                    raw_port = item.get("port") or item.get("service_port") or port
                    try:
                        job_port = int(raw_port)
                    except (TypeError, ValueError):
                        job_port = port
                    jobs.append({**item, "port": job_port})
                self.job_index.upsert(cache_principal, jobs)
                return {
                    **value,
                    "success": True,
                    "scope": scope,
                    "jobs": jobs,
                    "page": value.get("page", requested_page),
                }
            except (ConnectionError, OSError, TypeError, ValueError):
                continue

        cached = self.job_index.page(
            cache_principal, page=requested_page, limit=bounded_limit,
        )
        return {
            **cached,
            "success": True,
            "scope": scope,
            "stale": bool(cached["jobs"]),
        }

    def _worktree_entries(self) -> list[dict[str, str]]:
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
        """Remove disposable detached worktrees and prune stale metadata."""
        try:
            entries = self._worktree_entries()
        except (OSError, subprocess.CalledProcessError):
            return []
        removed: list[Path] = []
        for entry in entries:
            if entry.get("branch"):
                continue
            raw_path = entry.get("worktree")
            if not raw_path:
                continue
            worktree_path = Path(raw_path).resolve()
            if worktree_path == self.repo:
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
        entries = self._worktree_entries()

        result: list[Worktree] = []
        for entry in entries:
            path = Path(entry.get("worktree", "")).resolve()
            if not path:
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

            result.append(Worktree(
                path=path, branch=branch, head=head,
                label=branch, port=port,
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
        script = path / "scripts/worktree_flask_manager.py"
        if not script.is_file():
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
        socket_path = path / ".workspace" / "runtime" / f"{deployment_id}.sock"
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
        if worktree is None or worktree.port == 0 or not port_in_use(worktree.port):
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

    def start_vibe(self) -> str:
        if self.vibe_running():
            return "Vibe-Trading already running"
        if port_in_use(VIBE_TRADING_PORT):
            raise RuntimeError(
                f"Vibe-Trading port {VIBE_TRADING_PORT} is already in use"
            )
        executable = VIBE_TRADING_ROOT / ".conda" / "bin" / "vibe-trading"
        if not executable.is_file():
            raise RuntimeError(f"missing Vibe-Trading executable: {executable}")
        log_file = self.log_dir / f"vibe-trading-{VIBE_TRADING_PORT}.log"
        log = log_file.open("ab", buffering=0)
        self.vibe_process = subprocess.Popen(
            [
                str(executable),
                "serve",
                "--host", "127.0.0.1",
                "--port", str(VIBE_TRADING_PORT),
            ],
            cwd=VIBE_TRADING_ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        return f"started Vibe-Trading pid {self.vibe_process.pid}"

    def stop_vibe(self) -> str:
        process = self.vibe_process
        if process is None or process.poll() is not None:
            self.vibe_process = None
            return "Vibe-Trading not running"
        self._terminate(process)
        self.vibe_process = None
        return "stopped Vibe-Trading"

    def _service_env(self, path: Path, port: int) -> tuple[dict[str, str], str, Path]:
        deployment_id = f"{safe_name(path.name)}-{port}"
        socket_path = path / ".workspace" / "runtime" / f"{deployment_id}.sock"
        env = os.environ.copy()
        harness_root = str(
            (path / "tools" / "cli" / "agent-harness").resolve()
        )
        python_path = [
            item
            for item in env.get("PYTHONPATH", "").split(os.pathsep)
            if item
        ]
        if harness_root not in python_path:
            python_path.insert(0, harness_root)
        env.update({
            "FLASK_DEBUG": "1",
            "FACTORTESTER_WERKZEUG_RELOADER": "0",
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": os.pathsep.join(python_path),
            "GTHT_DEPLOYMENT_ID": deployment_id,
            "GTHT_JOB_DAEMON_SOCKET": str(socket_path),
            "GTHT_SOURCE_REVISION": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=path, text=True
            ).strip(),
            "GTHT_JOB_ARTIFACT_ROOT": str(self.data_root / "job-results"),
        })
        return env, deployment_id, socket_path

    def _start_api(self, path: Path, port: int, env: dict[str, str], log) -> subprocess.Popen:
        api_env = env.copy()
        api_env["GTHT_MANAGER_CAPABILITY_TOKEN"] = self.capability_token()
        return subprocess.Popen(
            [self.python, "start_server.py", "--port", str(port)],
            cwd=path,
            env=api_env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def start(self, path: Path, port: int) -> str:
        path = path.resolve()
        if self.is_running(path):
            return "already running"
        existing = self.processes.get(self.key(path))
        if existing is not None and existing.daemon.poll() is None:
            return self.restart_api(path, port)
        if existing is not None:
            self.processes.pop(self.key(path), None)
        if not (path / "start_server.py").exists():
            raise RuntimeError(f"missing start_server.py in {path}")
        if port == 0:
            raise RuntimeError(f"worktree has no assigned port (branch name lacks issue number)")
        if port_in_use(port):
            raise RuntimeError(f"port {port} is already in use")

        log_file = self.log_dir / f"{safe_name(path.name)}-{port}.log"
        log = log_file.open("ab", buffering=0)
        env, deployment_id, socket_path = self._service_env(path, port)
        daemon = subprocess.Popen(
            [
                self.python,
                "scripts/research_job_daemon.py",
                "--deployment-id", deployment_id,
                "--socket", str(socket_path),
            ],
            cwd=path,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        api = self._start_api(path, port, env, log)
        self.processes[self.key(path)] = ServiceBundle(
            api=api,
            daemon=daemon,
            socket_path=socket_path,
            deployment_id=deployment_id,
        )
        return f"started api pid {api.pid}, daemon pid {daemon.pid}"

    def restart_api(self, path: Path, port: int) -> str:
        path = path.resolve()
        bundle = self._bundle_for_path(path)
        if bundle is None or bundle.daemon.poll() is not None:
            raise RuntimeError("research daemon is not running")
        if bundle.api.poll() is None:
            self._terminate(bundle.api)
        log_file = self.log_dir / f"{safe_name(path.name)}-{port}.log"
        log = log_file.open("ab", buffering=0)
        env, _, _ = self._service_env(path, port)
        bundle.api = self._start_api(path, port, env, log)
        return f"restarted api pid {bundle.api.pid}; daemon pid {bundle.daemon.pid} preserved"

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)

    @staticmethod
    def _normalized_socket_path(path: Path) -> Path:
        resolved = path.expanduser().resolve()
        if len(str(resolved).encode()) <= 96:
            return resolved
        digest = hashlib.sha256(str(resolved).encode()).hexdigest()[:24]
        return Path(tempfile.gettempdir()) / "factortester-jobs" / f"{digest}.sock"

    def _daemon_request(self, bundle: ServiceBundle, action: str) -> dict:
        address = self._normalized_socket_path(bundle.socket_path)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            sock.connect(str(address))
            sock.sendall(json.dumps({"action": action}).encode() + b"\n")
            raw = sock.makefile("rb").readline()
        payload = json.loads(raw.decode())
        if not payload.get("success"):
            raise RuntimeError(payload.get("error") or "job daemon request failed")
        return payload

    def restart_bundle(self, path: Path, port: int, *, timeout: float = 120.0) -> str:
        path = path.resolve()
        bundle = self._bundle_for_path(path)
        if bundle is None:
            return self.start(path, port)
        if bundle.daemon.poll() is not None:
            self._terminate(bundle.api)
            self._terminate(bundle.daemon)
            self.processes.pop(self.key(path), None)
            return self.start(path, port)
        health = self._daemon_request(bundle, "drain")
        if health.get("paused_jobs"):
            self._daemon_request(bundle, "resume")
            raise RuntimeError("paused step jobs block bundle restart; cancel them or use Force Stop")
        deadline = time.monotonic() + max(1.0, float(timeout))
        while int(health.get("active_planners") or 0) or int(health.get("active_executors") or 0):
            if time.monotonic() >= deadline:
                self._daemon_request(bundle, "resume")
                raise TimeoutError("timed out draining research workers")
            time.sleep(0.2)
            health = self._daemon_request(bundle, "health")
            if health.get("paused_jobs"):
                self._daemon_request(bundle, "resume")
                raise RuntimeError("job paused during drain; cancel it or use Force Stop")
        self._terminate(bundle.api)
        self._terminate(bundle.daemon)
        self.processes.pop(self.key(path), None)
        return self.start(path, port)

    def stop(self, path: Path, *, force: bool = False) -> str:
        path = path.resolve()
        bundle = self._bundle_for_path(path)
        if not bundle:
            self.processes.pop(self.key(path), None)
            return "not running"
        if not force and bundle.daemon.poll() is None:
            health = self._daemon_request(bundle, "health")
            active = int(health.get("active_planners") or 0) + int(health.get("active_executors") or 0)
            if active:
                raise RuntimeError("active research jobs block Stop; use Restart Bundle or Force Stop")
        self._terminate(bundle.api)
        self._terminate(bundle.daemon)
        self.processes.pop(self.key(path), None)
        return "stopped"

    def stop_all(self) -> None:
        for key in list(self.processes):
            bundle = self.processes.get(key)
            if bundle:
                self.stop(Path(key), force=True)
        self.processes.clear()
        self.stop_vibe()


def _lan_ip() -> str:
    """Return LAN IP or 'localhost' if unavailable."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.0)
        s.connect(("8.8.8.8", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def _authenticate_user(username: str, password: str) -> tuple[str, str]:
    from tools.data.account_manage import (
        accounts_lock,
        is_super_admin_account,
        load_accounts,
        verify_password,
    )

    username = str(username or "").strip()
    password = str(password or "")
    if not username or not password:
        raise ValueError("username and password are required")
    with accounts_lock:
        accounts = load_accounts()
    account = next(
        (item for item in accounts if item.get("username") == username),
        None,
    )
    if account is None:
        matches = [
            item for item in accounts
            if item.get("alias", item.get("username")) == username
        ]
        if len(matches) == 1:
            account = matches[0]
    if (
        account is None
        or not verify_password(
            password,
            str(account.get("salt") or ""),
            str(account.get("hash") or ""),
        )
    ):
        raise PermissionError("invalid username or password")
    role = (
        "super_admin" if is_super_admin_account(account)
        else str(account.get("role") or "user")
    )
    return str(account["username"]), role


def _manager_subordinate_users(owner: str) -> list[dict[str, str]]:
    """Return the account choices without asking a service port to enumerate them."""
    from tools.data.account_manage import visible_accounts_for

    result: list[dict[str, str]] = []
    for account in visible_accounts_for(owner, include_self=False):
        username = str(account.get("username") or "").strip()
        if not username:
            continue
        alias = str(account.get("alias") or "").strip()
        result.append({
            "username": username,
            "alias": alias,
            "title": alias or username,
            "organization_name": str(account.get("organization_name") or ""),
            "role": str(account.get("role") or "user"),
        })
    return sorted(result, key=lambda item: (item["title"].lower(), item["username"]))


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value) or "worktree"


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def json_response(
    handler: BaseHTTPRequestHandler,
    payload: dict,
    status: int = 200,
    *,
    headers: dict[str, str] | None = None,
) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    for key, value in (headers or {}).items():
        handler.send_header(key, value)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def page(state: ManagerState, message: str = "") -> bytes:
    lan = _lan_ip()
    rows = []
    for wt in state.worktrees():
        instance_id = state.instance_id(wt)
        if wt.port == 0:
            # No issue number — show warning, no Start/Stop actions
            rows.append(
                f"""
            <tr class="orphan">
              <td><strong>{html.escape(wt.label)}</strong><div class="muted">{html.escape(wt.branch)} · {html.escape(wt.head)}</div></td>
              <td><code>{html.escape(instance_id)}</code></td>
              <td><span class="muted">—</span></td>
              <td><span class="pill orphan-pill">no-issue</span></td>
              <td><span class="muted">⚠️ 建议清理：分支名不含 issue 编号</span></td>
            </tr>
            """
            )
            continue
        running = state.is_running(wt.path)
        occupied = port_in_use(wt.port) and not running
        daemon_running = state.daemon_running(wt.path)
        status = "running" if running and daemon_running else ("degraded" if running else ("occupied" if occupied else "stopped"))
        start_disabled = "disabled" if running or occupied else ""
        stop_disabled = "" if running or daemon_running else "disabled"
        open_disabled = "" if running or occupied else "disabled"
        rows.append(
            f"""
            <tr>
              <td><strong>{html.escape(wt.label)}</strong><div class="muted">{html.escape(wt.branch)} · {html.escape(wt.head)}</div></td>
              <td><code>{html.escape(instance_id)}</code></td>
              <td><a href="http://localhost:{wt.port}/" target="_blank" title="localhost">{wt.port}</a> <span class="muted">|</span> <a href="http://{lan}:{wt.port}/" target="_blank" title="LAN ({lan})" class="lan-link">🌐</a></td>
              <td><span class="pill {status}">{status}</span></td>
              <td>
                <form method="post" action="/start"><input type="hidden" name="instance_id" value="{html.escape(instance_id)}"><button {start_disabled}>Start</button></form>
                <form method="post" action="/stop"><input type="hidden" name="instance_id" value="{html.escape(instance_id)}"><button {stop_disabled}>Stop</button></form>
                <form method="post" action="/restart-api"><input type="hidden" name="instance_id" value="{html.escape(instance_id)}"><button {'' if daemon_running else 'disabled'}>Restart API</button></form>
                <form method="post" action="/restart-bundle"><input type="hidden" name="instance_id" value="{html.escape(instance_id)}"><button {'' if daemon_running else 'disabled'}>Restart Bundle</button></form>
                <form method="post" action="/force-stop"><input type="hidden" name="instance_id" value="{html.escape(instance_id)}"><button {stop_disabled}>Force Stop</button></form>
                <a class="button {open_disabled}" href="http://localhost:{wt.port}/" target="_blank">Open</a>
                <a class="button {open_disabled}" href="http://{lan}:{wt.port}/" target="_blank" title="LAN 访问">🌐 Open</a>
              </td>
            </tr>
            """
        )
    msg = f"<div class='message'>{html.escape(message)}</div>" if message else ""
    vibe_running = state.vibe_running()
    vibe_occupied = port_in_use(VIBE_TRADING_PORT) and not vibe_running
    vibe_status = (
        "running" if vibe_running else "occupied" if vibe_occupied else "stopped"
    )
    vibe_start_disabled = "disabled" if vibe_running or vibe_occupied else ""
    vibe_stop_disabled = "" if vibe_running else "disabled"
    vibe_open_disabled = "" if vibe_running or vibe_occupied else "disabled"
    vibe_row = f"""
      <tr>
        <td><strong>Vibe-Trading</strong><div class="muted">research UI + MaxA MCP gateway</div></td>
        <td><code>service-vibe-trading</code></td>
        <td><a href="http://localhost:{VIBE_TRADING_PORT}/" target="_blank">{VIBE_TRADING_PORT}</a></td>
        <td><span class="pill {vibe_status}">{vibe_status}</span></td>
        <td>
          <form method="post" action="/vibe/start"><input type="hidden" name="instance_id" value="service-vibe-trading"><button {vibe_start_disabled}>Start</button></form>
          <form method="post" action="/vibe/stop"><input type="hidden" name="instance_id" value="service-vibe-trading"><button {vibe_stop_disabled}>Stop</button></form>
          <a class="button {vibe_open_disabled}" href="http://localhost:{VIBE_TRADING_PORT}/" target="_blank">Open</a>
        </td>
      </tr>
    """
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>FactorTester Worktree Flask Manager</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #1f2937; }}
    h1 {{ font-size: 22px; margin: 0 0 16px; }}
    table {{ border-collapse: collapse; width: 100%; table-layout: fixed; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 10px; text-align: left; vertical-align: top; }}
    th:nth-child(1), td:nth-child(1) {{ width: auto; }}
    th:nth-child(2), td:nth-child(2) {{ width: auto; }}
    th:nth-child(3), td:nth-child(3) {{ width: 85px; }}
    th:nth-child(4), td:nth-child(4) {{ width: 85px; }}
    th:nth-child(5), td:nth-child(5) {{ width: 280px; white-space: nowrap; }}
    th {{ background: #f9fafb; font-size: 12px; text-transform: uppercase; color: #6b7280; }}
    code {{ font-size: 12px; color: #374151; word-break: break-all; }}
    form {{ display: inline; }}
    button, .button {{ border: 1px solid #cbd5e1; background: #fff; color: #111827; padding: 4px 9px; border-radius: 6px; text-decoration: none; font-size: 13px; cursor: pointer; margin-right: 4px; }}
    button:disabled, .disabled {{ opacity: .45; pointer-events: none; cursor: default; }}
    .muted {{ color: #6b7280; font-size: 12px; margin-top: 2px; }}
    .pill {{ display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 12px; font-weight: 600; }}
    .running {{ background: #dcfce7; color: #166534; }}
    .stopped {{ background: #f3f4f6; color: #374151; }}
    .occupied {{ background: #fef3c7; color: #92400e; }}
    .degraded {{ background: #fee2e2; color: #991b1b; }}
    .orphan {{ background: #fef2f2; }}
    .orphan-pill {{ background: #fee2e2; color: #991b1b; }}
    .message {{ padding: 8px 10px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px; margin-bottom: 12px; }}
    .lan-link {{ text-decoration: none; font-size: 14px; }}
  </style>
</head>
<body>
  <h1>FactorTester Worktree Flask Manager</h1>
  <p class="muted" style="margin-bottom:4px">Use Start/Stop for ordinary parallel servers. For VS Code breakpoints, launch the matching <code>Flask Debug: ...</code> configuration on the same worktree/port while that port is stopped here.</p>
  <p class="muted" style="margin-bottom:12px">🌐 局域网访问本机: <strong>{lan}</strong>（同一热点/网络下的设备使用此 IP + 端口号访问）</p>
  {msg}
  <table>
    <thead><tr><th>Worktree</th><th>Instance</th><th>Port</th><th>Status</th><th>Actions</th></tr></thead>
    <tbody>{vibe_row}{''.join(rows)}</tbody>
  </table>
</body>
</html>""".encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    state: ManagerState

    def _client_ip(self) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
        peer = ipaddress.ip_address(self.client_address[0])
        if not peer.is_loopback:
            return peer
        forwarded = self.headers.get(
            "X-Forwarded-For", ""
        ).split(",", 1)[0].strip()
        if not forwarded:
            return peer
        try:
            return ipaddress.ip_address(forwarded)
        except ValueError:
            return peer

    def _is_loopback_client(self) -> bool:
        return self._client_ip().is_loopback

    def _is_private_lan_client(self) -> bool:
        client = self._client_ip()
        return client.is_private or client.is_link_local

    def _is_https_proxy_request(self) -> bool:
        try:
            peer = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        forwarded_proto = self.headers.get(
            "X-Forwarded-Proto", ""
        ).split(",", 1)[0].strip().lower()
        return peer.is_loopback and forwarded_proto == "https"

    def _has_secure_ui_transport(self) -> bool:
        return (
            self._is_loopback_client()
            or self._is_private_lan_client()
            or self._is_https_proxy_request()
        )

    def _is_same_origin_browser_action(self) -> bool:
        if not self._is_loopback_client():
            return False
        origin = self.headers.get("Origin", "").rstrip("/")
        host = self.headers.get("Host", "").strip()
        return bool(origin and host and origin == f"http://{host}")

    def _has_capability(self) -> bool:
        supplied = self._bearer_token()
        return (
            bool(supplied)
            and hmac.compare_digest(supplied, self.state.capability_token())
        )

    def _bearer_token(self) -> str:
        scheme, _, supplied = self.headers.get("Authorization", "").partition(" ")
        if scheme.lower() == "bearer" and supplied:
            return supplied.strip()
        # Embedded documentation/database pages are ordinary browser
        # navigations and cannot attach the SPA Authorization header.  The
        # Manager login cookie is HttpOnly and is therefore only parsed here.
        for item in self.headers.get("Cookie", "").split(";"):
            name, separator, value = item.strip().partition("=")
            if separator and name == "ft-manager-session":
                return value.strip()
        return ""

    def _session(self) -> dict[str, object] | None:
        return self.state.session(self._bearer_token())

    def _has_manager_ui_session(self) -> bool:
        session = self.state.session(self._bearer_token())
        return bool(
            self._has_secure_ui_transport() and session
            and session["capabilities"]["manager"]
        )

    def _has_api_authorization(self) -> bool:
        return self._has_capability() or self._has_manager_ui_session()

    def _require_capability(self) -> bool:
        if self._has_capability():
            return True
        self.send_response(401)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("WWW-Authenticate", "Bearer")
        body = b'{"error":"manager capability required"}'
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def _job_ports(self, parsed, principal: str | None = None) -> list[int]:
        requested = parse_qs(parsed.query).get("port", [""])[0]
        indexed: list[int] = []
        if principal:
            match = re.fullmatch(
                r"/api/jobs/([A-Za-z0-9._-]{1,128})", parsed.path,
            )
            if match:
                indexed = self.state.job_index.ports_for(
                    principal, unquote(match.group(1)),
                )
        if requested.isdigit():
            port = int(requested)
            running = self.state.service_ports()
            # A cached job can outlive the service instance that created it.
            # Do not turn a stale/invalid port hint into a false 404; the
            # manager still owns the cross-port lookup and can find the job on
            # its currently running service.
            if port in running:
                return list(dict.fromkeys([*indexed, port]))
            return list(dict.fromkeys([*indexed, *running]))
        return list(dict.fromkeys([*indexed, *self.state.service_ports()]))

    def _service_port(self, parsed) -> int | None:
        requested = parse_qs(parsed.query).get("port", [""])[0]
        if requested.isdigit():
            value = int(requested)
            return value if value in self.state.service_ports() else None
        return self.state.preferred_service_port()

    @staticmethod
    def _forwarded_service_path(parsed) -> str:
        query = urlencode([
            (key, value) for key, value in parse_qsl(
                parsed.query, keep_blank_values=True,
            ) if key != "port"
        ])
        return parsed.path + (f"?{query}" if query else "")

    def _proxy_service_get(self, parsed) -> bool:
        if not any(parsed.path.startswith(prefix) for prefix in _SERVICE_GET_PREFIXES):
            return False
        session = self._session()
        public_graph = (
            session is None and _PUBLIC_GRAPH_READ_RE.fullmatch(parsed.path)
        )
        public_docs = (
            parsed.path == "/docs"
            or parsed.path.startswith("/docs/")
            or parsed.path.startswith("/static/css/")
            or parsed.path.startswith("/static/js/")
            or parsed.path.startswith("/static/vendor/")
            or parsed.path.startswith("/static/images/")
        )
        if session is None and not (public_graph or public_docs):
            json_response(
                self, {"success": False, "error": "login required"}, 401,
            )
            return True
        port = self._service_port(parsed)
        if port is None:
            json_response(
                self, {"success": False, "error": "service port is unavailable"}, 502,
            )
            return True
        try:
            response = self.state.gateway.request(
                port=port,
                path=self._forwarded_service_path(parsed),
                principal=(
                    "__public_graph__" if public_graph
                    else "__public_docs__" if public_docs
                    else str(session["username"])
                ),
            )
        except (ConnectionError, ValueError):
            json_response(
                self, {"success": False, "error": "service port is unavailable"}, 502,
            )
            return True
        self._send_gateway_response(response, port=port)
        return True

    def _proxy_service_write(self, parsed, *, method: str) -> bool:
        patterns = _SERVICE_WRITE_PATTERNS.get(method, ())
        if not any(re.fullmatch(pattern, parsed.path) for pattern in patterns):
            return False
        session = self._session()
        if session is None:
            json_response(
                self, {"success": False, "error": "login required"}, 401,
            )
            return True
        port = self._service_port(parsed)
        if port is None:
            json_response(
                self, {"success": False, "error": "service port is unavailable"}, 502,
            )
            return True
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1024 * 1024:
            json_response(
                self, {"success": False, "error": "invalid request body"}, 400,
            )
            return True
        body = self.rfile.read(length)
        try:
            response = self.state.gateway.request(
                port=port,
                path=self._forwarded_service_path(parsed),
                principal=str(session["username"]),
                method=method,
                body=body,
                content_type=str(self.headers.get("Content-Type") or "application/json"),
            )
        except (ConnectionError, ValueError):
            json_response(
                self, {"success": False, "error": "service port is unavailable"}, 502,
            )
            return True
        self._send_gateway_response(response, port=port)
        return True

    def _send_gateway_response(
        self, response: GatewayResponse, *, port: int,
    ) -> None:
        body = response.body
        content_type = response.content_type
        if content_type == "application/json":
            try:
                value = response.json_object()
                value.setdefault("port", port)
                body = json.dumps(value, ensure_ascii=False).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
                pass
        self.send_response(response.status)
        self.send_header("Content-Type", content_type)
        if response.content_disposition:
            self.send_header(
                "Content-Disposition", response.content_disposition,
            )
        if response.etag:
            self.send_header("ETag", response.etag)
        self.send_header("X-FactorTester-Service-Port", str(port))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _proxy_job_request(self, parsed, *, method: str) -> bool:
        match = re.fullmatch(
            r"/api/jobs/([A-Za-z0-9._-]{1,128})"
            r"(/result|/artifacts(?:/archive|/[^/]{1,512}(?:/preview)?)?)?",
            parsed.path,
        )
        if match is None:
            return False
        session = self._session()
        suffix_value = match.group(2) or ""
        public = (
            session is None
            and method == "GET"
            and (suffix_value in {"", "/result", "/artifacts"}
                 or suffix_value.endswith("/preview"))
        )
        if session is None and not public:
            json_response(
                self, {"success": False, "error": "login required"}, 401,
            )
            return True
        if public:
            principal = "__public_jobs__"
        else:
            principal = str(session["username"])
        job_id = quote(unquote(match.group(1)), safe="")
        suffix = match.group(2) or ""
        if ".." in unquote(suffix).split("/"):
            json_response(
                self, {"success": False, "error": "invalid artifact name"}, 400,
            )
            return True
        path = f"/api/jobs/{job_id}{suffix}"
        last_response: tuple[int, GatewayResponse] | None = None
        for port in self._job_ports(parsed, principal):
            try:
                response = self.state.gateway.request(
                    port=port,
                    path=path,
                    principal=principal,
                    method=method,
                )
            except (ConnectionError, ValueError):
                continue
            last_response = (port, response)
            if response.status == 404:
                continue
            self._send_gateway_response(response, port=port)
            return True
        if last_response is not None:
            self._send_gateway_response(
                last_response[1],
                port=last_response[0],
            )
            return True
        json_response(
            self, {"success": False, "error": "job was not found"}, 404,
        )
        return True

    def _proxy_job_stream(self, parsed) -> bool:
        match = re.fullmatch(
            r"/api/jobs/([A-Za-z0-9._-]{1,128})/stream", parsed.path,
        )
        if match is None:
            return False
        session = self._session()
        public = session is None
        principal = "__public_jobs__" if public else str(session["username"])
        path = self._forwarded_service_path(parsed)
        job_id = unquote(match.group(1))
        last_error: HTTPError | None = None
        for port in self._job_ports(parsed, principal):
            request = Request(
                f"http://127.0.0.1:{port}{path}",
                headers={
                    "Accept": "text/event-stream",
                    "X-FactorTester-Principal": principal,
                    "X-FactorTester-Manager": self.state.capability_token(),
                    "Last-Event-ID": str(self.headers.get("Last-Event-ID") or ""),
                },
            )
            try:
                upstream = urlopen(request, timeout=15)
            except HTTPError as exc:
                last_error = exc
                if exc.code == 404:
                    continue
                body = exc.read()
                self.send_response(exc.code)
                self.send_header("Content-Type", exc.headers.get_content_type())
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return True
            except URLError:
                continue
            with upstream:
                self.send_response(upstream.status)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("X-FactorTester-Service-Port", str(port))
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    event_buffer = b""
                    while chunk := upstream.read(4096):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        event_buffer = (event_buffer + chunk).replace(b"\r\n", b"\n")
                        while b"\n\n" in event_buffer:
                            frame, event_buffer = event_buffer.split(b"\n\n", 1)
                            data = b"\n".join(
                                line[5:].strip()
                                for line in frame.splitlines()
                                if line.startswith(b"data:")
                            )
                            if not data:
                                continue
                            try:
                                event = json.loads(data.decode("utf-8"))
                            except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
                                continue
                            if isinstance(event, dict):
                                self.state.job_index.upsert(principal, [{
                                    **event,
                                    "job_id": str(event.get("job_id") or job_id),
                                    "port": port,
                                    "updated_at": str(event.get("updated_at") or time.time()),
                                }])
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    pass
                return True
        if last_error is not None:
            body = last_error.read()
            self.send_response(last_error.code)
            self.send_header("Content-Type", last_error.headers.get_content_type())
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        json_response(
            self, {"success": False, "error": "job stream was not found"}, 404,
        )
        return True

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        locale_match = re.fullmatch(
            r"/api/localizations/(zh-Hans|en)", parsed.path,
        )
        if locale_match:
            try:
                value = web_localization(
                    _REPO_ROOT / "apple/Resources/Shared/Localizable.xcstrings",
                    locale_match.group(1),
                )
            except (OSError, ValueError, json.JSONDecodeError):
                json_response(self, {"success": False, "error": "localization catalog is unavailable"}, 503)
                return
            json_response(self, value)
            return
        if parsed.path.startswith("/research-static/"):
            try:
                body, content_type = static_file(
                    parsed.path.removeprefix("/research-static/"),
                )
            except ValueError:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("X-Content-Type-Options", "nosniff")
            # 7998 serves the web shell directly from the selected worktree.
            # Do not cache source assets: a changed JS/CSS file is visible on
            # the next navigation without restarting the manager process.
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/static/config/modules.json":
            try:
                body = (_REPO_ROOT / "static/config/modules.json").read_bytes()
                json.loads(body.decode("utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                json_response(
                    self,
                    {"success": False, "error": "module manifest is unavailable"},
                    503,
                )
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self._serve_client_release(parsed.path):
            return
        if parsed.path == "/api/modules":
            session = self._session()
            manager = bool(
                session and session["capabilities"]["manager"]
            )
            modules = [
                {"id": "home", "title": "主页", "title_key": "主页", "icon": "grid", "sfSymbol": "square.grid.2x2"},
                {"id": "research", "title": "研究", "title_key": "研究", "icon": "chart", "sfSymbol": "chart.xyaxis.line"},
                {"id": "ic-test", "title": "IC 测试", "title_key": "IC 测试", "icon": "correlation", "sfSymbol": "chart.xyaxis.line"},
                {"id": "backtest", "title": "回测", "title_key": "回测", "icon": "backtest", "sfSymbol": "chart.line.uptrend.xyaxis"},
                {"id": "jobs", "title": "测试任务", "title_key": "测试任务", "icon": "checklist", "sfSymbol": "checklist"},
                {"id": "factors", "title": "因子库", "title_key": "因子库", "icon": "function", "sfSymbol": "function"},
                {"id": "products", "title": "产品", "title_key": "产品", "icon": "box", "sfSymbol": "shippingbox"},
                {"id": "profiles", "title": "Profiles", "title_key": "Profiles", "icon": "profiles", "sfSymbol": "person.2.crop.square.stack"},
                {"id": "sqlite_web", "title": "数据库", "title_key": "数据库", "icon": "SQL", "sfSymbol": "cylinder.split.1x2", "path": "/sqlite-web/", "requiresAuth": True},
                {"id": "docs", "title": "技术文档", "title_key": "技术文档", "icon": "book", "sfSymbol": "book", "path": "/docs", "requiresAuth": False},
                {"id": "settings", "title": "设置", "title_key": "设置", "icon": "settings", "sfSymbol": "person.crop.circle"},
            ]
            if manager:
                modules.append({
                    "id": "manager", "title": "服务器管理", "title_key": "服务器管理", "icon": "server", "sfSymbol": "server.rack",
                })
            json_response(self, {"modules": modules})
            return
        if parsed.path == "/api/jobs/ports":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            json_response(self, {
                "ports": self.state.service_ports(),
                "automatic_port": self.state.preferred_service_port(),
            })
            return
        if parsed.path == "/api/jobs":
            session = self._session()
            query = parse_qs(parsed.query, keep_blank_values=True)
            scope = str(query.get("scope", [""])[0] or "").strip().lower()
            if not scope:
                if session is None or str(session.get("role") or "") == "super_admin":
                    scope = "server"
                else:
                    scope = "mine"
            if session is None and scope != "server":
                # Keep the three scopes visible in the web client without
                # asking an anonymous request to discover private accounts.
                json_response(self, {
                    "success": True,
                    "scope": scope,
                    "requires_login": True,
                    "jobs": [],
                    "page": 1,
                    "page_size": 20,
                    "total": 0,
                    "total_pages": 1,
                    "has_more": False,
                    "next_cursor": None,
                })
                return
            try:
                limit = int(query.get("limit", ["20"])[0] or 20)
            except (TypeError, ValueError):
                json_response(self, {
                    "success": False,
                    "error": "limit 必须是整数",
                }, 400)
                return
            if session is None:
                limit = min(limit, 20)
                principal = "__public_jobs__"
            else:
                principal = str(session["username"])
            if scope == "server":
                # Server history is a public projection backed by the shared
                # job repository.  Keep its cache fallback so a stale
                # service process cannot turn the whole task page into 502.
                cursor = str(query.get("cursor", [""])[0] or "")
                if session is not None and str(session.get("role") or "") == "super_admin":
                    payload = self.state.aggregate_server_jobs(
                        principal=principal, cursor=cursor, limit=limit,
                    )
                else:
                    payload = self.state.aggregate_public_jobs(
                        cursor=cursor, limit=limit,
                    )
                payload.setdefault("success", True)
                payload.setdefault("scope", scope)
                fallback_port = None
                for item in payload.get("jobs") or ():
                    if isinstance(item, dict):
                        if "port" not in item:
                            if fallback_port is None:
                                fallback_port = self.state.preferred_service_port() or 0
                            item["port"] = fallback_port
                json_response(self, payload)
                return
            try:
                requested_page = max(1, int(query.get("page", ["1"])[0] or 1))
            except (TypeError, ValueError):
                json_response(self, {
                    "success": False, "error": "page 必须是整数",
                }, 400)
                return
            if scope == "mine":
                payload = self.state.aggregate_account_jobs(
                    principal=principal,
                    scope=scope,
                    page=requested_page,
                    limit=limit,
                )
            elif scope == "subordinates":
                users = _manager_subordinate_users(principal)
                requested_user = str(
                    query.get("username", query.get("user", [""]))[0] or "",
                ).strip()
                base = {
                    "success": True,
                    "scope": scope,
                    "users": users,
                }
                if not requested_user:
                    json_response(self, {
                        **base,
                        "selection_required": True,
                        "jobs": [],
                        "page": 1,
                        "page_size": 20,
                        "total": 0,
                        "total_pages": 1,
                        "has_more": False,
                        "next_cursor": None,
                    })
                    return
                allowed = {item["username"] for item in users}
                if requested_user not in allowed:
                    json_response(self, {
                        "success": False, "error": "无权查看该下级用户任务",
                    }, 403)
                    return
                payload = self.state.aggregate_account_jobs(
                    principal=principal,
                    scope=scope,
                    username=requested_user,
                    page=requested_page,
                    limit=limit,
                )
                payload["users"] = users
            else:
                json_response(self, {
                    "success": False, "error": "不支持的任务范围",
                }, 400)
                return
            payload["success"] = True
            payload["scope"] = scope
            json_response(self, payload)
            return
        if self._proxy_job_stream(parsed):
            return
        if self._proxy_job_request(parsed, method="GET"):
            return
        if parsed.path == "/api/client/profiles":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            json_response(self, {
                "profiles": self.state.client_state.profiles(
                    str(session["username"]),
                ),
            })
            return
        if parsed.path == "/api/client/workspace":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            json_response(self, {
                "workspace": self.state.client_state.workspace(
                    str(session["username"]),
                ),
            })
            return
        if parsed.path == "/api/client/research":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            json_response(self, {
                "success": True,
                "research": self.state.client_state.local_research(
                    str(session["username"]),
                ),
            })
            return
        local_research_match = re.fullmatch(
            r"/api/client/research/([^/]+)", parsed.path,
        )
        if local_research_match:
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            try:
                value = self.state.client_state.local_research_report(
                    str(session["username"]),
                    unquote(local_research_match.group(1)),
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except (OSError, ValueError, KeyError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return
            json_response(self, {"success": True, **value})
            return
        if parsed.path == "/api/client/preferences":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            json_response(self, {
                "preferences": self.state.user_preferences.read(
                    str(session["username"]),
                ),
            })
            return
        if self._proxy_service_get(parsed):
            return
        if parsed.path == "/api/public-research":
            session = self._session()
            viewer = str(session["username"]) if session else None
            json_response(self, {
                "reports": self.state.public_research.list_visible(viewer),
            })
            return
        public_match = re.fullmatch(
            r"/api/public-research/([A-Za-z0-9_-]{20,64})", parsed.path,
        )
        if public_match:
            session = self._session()
            viewer = str(session["username"]) if session else None
            try:
                value = self.state.public_research.projection(
                    public_match.group(1), viewer,
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return
            etag = '"' + str(value["projection_hash"]) + '"'
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.end_headers()
                return
            self.send_response(200)
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "private, no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        asset_match = re.fullmatch(
            r"/api/public-research/([A-Za-z0-9_-]{20,64})/assets/([A-Za-z0-9_-]{8,64})",
            parsed.path,
        )
        if asset_match:
            session = self._session()
            viewer = str(session["username"]) if session else None
            try:
                raw, content_type, filename = self.state.public_research.asset(
                    asset_match.group(1), asset_match.group(2), viewer,
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'inline; filename="{filename}"')
            self.send_header("Cache-Control", "private, no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        local_resource_match = re.fullmatch(
            r"/api/public-research/([A-Za-z0-9_-]{20,64})/local-resources/([a-f0-9]{24})",
            parsed.path,
        )
        if local_resource_match:
            session = self._session()
            viewer = str(session["username"]) if session else None
            try:
                raw, content_type, filename = self.state.public_research.local_resource(
                    local_resource_match.group(1), local_resource_match.group(2), viewer,
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return
            safe_filename = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name) or "resource"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            disposition = "inline" if parse_qs(parsed.query).get("inline") == ["1"] else "attachment"
            self.send_header("Content-Disposition", f'{disposition}; filename="{safe_filename}"')
            self.send_header("Cache-Control", "private, no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        attachment_match = re.fullmatch(
            r"/api/public-research/([A-Za-z0-9_-]{20,64})/attachments/(?:attachment%3Asha256%3A|attachment:sha256:)?([a-f0-9]{64})",
            parsed.path,
        )
        if attachment_match:
            session = self._session()
            viewer = str(session["username"]) if session else None
            try:
                raw, content_type, filename = self.state.public_research.attachment(
                    attachment_match.group(1),
                    f"attachment:sha256:{attachment_match.group(2)}",
                    viewer,
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "private, no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if parsed.path == "/api/research-publications/settings":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            json_response(self, {
                "reports": self.state.public_research.list_owner(
                    str(session["username"]),
                ),
            })
            return
        if parsed.path == "/api/session":
            session = self.state.session(self._bearer_token())
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            json_response(self, {"success": True, **session})
            return
        if parsed.path == "/api/worktrees":
            if not self._has_api_authorization():
                self._require_capability()
                return
            data = [
                {
                    "instance_id": self.state.instance_id(wt),
                    "label": wt.label,
                    "branch": wt.branch,
                    "head": wt.head,
                    "port": wt.port,
                    "running": self.state.is_running(wt.path),
                    "daemon_running": self.state.daemon_running(wt.path),
                    "port_in_use": port_in_use(wt.port),
                }
                for wt in self.state.worktrees()
            ]
            json_response(self, {
                "worktrees": data,
                "manager": {
                    "loopback_ip": "127.0.0.1",
                    "lan_ip": _lan_ip(),
                    "release_root": str(self.state.release_root),
                },
                "vibe_trading": {
                    "instance_id": "service-vibe-trading",
                    "port": VIBE_TRADING_PORT,
                    "running": self.state.vibe_running(),
                    "port_in_use": port_in_use(VIBE_TRADING_PORT),
                },
            })
            return
        shell_paths = {
            "/", "/research", "/jobs", "/factors", "/products",
            "/profiles", "/settings", "/manager", "/research-graphs",
            "/ic-test", "/backtest", "/test-templates",
        }
        if (
            parsed.path in shell_paths
            or parsed.path.startswith("/research/")
            or parsed.path.startswith("/jobs/")
            or parsed.path.startswith("/factors/")
            or parsed.path.startswith("/products/")
            or parsed.path.startswith("/profiles/")
            or parsed.path.startswith("/settings/")
            or parsed.path.startswith("/research-graphs/")
            or parsed.path.startswith("/ic-test/")
            or parsed.path.startswith("/backtest/")
            or parsed.path.startswith("/test-templates/")
        ):
            body = shell_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            # Artifact previews are fetched as authenticated blobs before they
            # are assigned to an <img>.  Keep the shell same-origin-only while
            # explicitly permitting those object URLs; without this WebKit
            # silently reports the preview as unreadable even though /preview
            # returned a valid image.
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob: data: https:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path != "/manager-legacy":
            self.send_error(404)
            return
        if not self._is_loopback_client():
            json_response(self, {"success": False, "error": "localhost required"}, 403)
            return
        message = parse_qs(parsed.query).get("message", [""])[0]
        body = page(self.state, message)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if self.path == "/auth/login":
            self._login()
            return
        if self.path == "/auth/register":
            self._register()
            return
        if self.path == "/auth/logout":
            token = self._bearer_token()
            if self.state.session_principal(token) is None:
                self._require_capability()
                return
            self.state.logout(token)
            json_response(
                self,
                {"success": True},
                headers={"Set-Cookie": self._session_cookie(token, clear=True)},
            )
            return
        if self.path == "/api/public-research/sync":
            if not self._is_loopback_client():
                json_response(self, {"success": False, "error": "local FTClient required"}, 403)
                return
            try:
                value = self.state.public_research.sync(self._json_body(32 * 1024 * 1024))
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
                return
            json_response(self, {"success": True, **value})
            return
        if self.path == "/api/public-research/publish":
            if not self._is_loopback_client():
                json_response(self, {"success": False, "error": "local FTClient required"}, 403)
                return
            try:
                payload = self._json_body(32 * 1024 * 1024)
                projection = payload.get("projection")
                report_id = str(payload.get("report_id") or "")
                owner_ref = str(payload.get("owner_ref") or "")
                if isinstance(projection, dict) and str(payload.get("public_title") or "").strip():
                    projection = {
                        **projection,
                        "title": str(payload["public_title"]).strip(),
                    }
                    # The title is part of the content-addressed projection.
                    # Recompute the hash after the optional public override so
                    # the list ETag and the mirrored payload describe the same
                    # bytes instead of retaining the local title's hash.
                    projection["projection_hash"] = hashlib.sha256(
                        json.dumps(
                            {
                                key: value
                                for key, value in projection.items()
                                if key != "projection_hash"
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()
                synced = self.state.public_research.sync({
                    "report_id": report_id,
                    "owner_ref": owner_ref,
                    "profile_ref": str(payload.get("profile_ref") or ""),
                    "projection": projection,
                })
                if synced.get("status") != "synced":
                    json_response(self, {"success": False, **synced}, 409)
                    return
                settings = self.state.public_research.configure(
                    owner_ref=owner_ref,
                    report_id=report_id,
                    projection=None,
                    visibility="public",
                    auto_sync=True,
                    relay_local_files=False,
                    authorized_users=[],
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except (TypeError, ValueError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
                return
            json_response(self, {
                "success": True,
                "status": "published",
                "publication_id": settings["publication_id"],
                "report_id": settings["report_id"],
                "visibility": settings["visibility"],
                "generation": settings.get("generation"),
                "projection_hash": projection["projection_hash"],
            })
            return
        if self.path == "/api/public-research/revoke":
            if not self._is_loopback_client():
                json_response(self, {"success": False, "error": "local FTClient required"}, 403)
                return
            try:
                payload = self._json_body(64 * 1024)
                value = self.state.public_research.revoke_publication(
                    str(payload.get("publication_id") or ""),
                )
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return
            json_response(self, {"success": True, **value})
            return
        if self.path == "/api/research-publications/settings":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            try:
                payload = self._json_body(256 * 1024)
                value = self.state.public_research.configure(
                    owner_ref=str(session["username"]),
                    report_id=str(payload.get("report_id") or ""),
                    projection=None,
                    visibility=str(payload.get("visibility") or "private"),
                    auto_sync=bool(payload.get("auto_sync", True)),
                    relay_local_files=bool(payload.get("relay_local_files", False)),
                    authorized_users=list(payload.get("authorized_users") or []),
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except (TypeError, ValueError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
                return
            json_response(self, {"success": True, "settings": value})
            return
        if self.path == "/api/client/preferences":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            try:
                value = self.state.user_preferences.update(
                    str(session["username"]),
                    self._json_body(64 * 1024),
                )
            except (TypeError, ValueError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
                return
            json_response(self, {"success": True, "preferences": value})
            return
        if self._proxy_service_write(parsed, method="POST"):
            return
        actions = {
            "/vibe/start",
            "/vibe/stop",
            "/start",
            "/stop",
            "/restart-api",
            "/restart-bundle",
            "/force-stop",
        }
        if self.path not in actions:
            self.send_error(404)
            return
        if not (
            self._has_api_authorization()
            or self._is_same_origin_browser_action()
        ):
            self._require_capability()
            return
        length = int(self.headers.get("Content-Length", "0"))
        params = parse_qs(self.rfile.read(length).decode("utf-8"))
        if set(params) != {"instance_id"} or len(params["instance_id"]) != 1:
            json_response(
                self,
                {"success": False, "error": "instance_id is required and is the only accepted target"},
                400,
            )
            return
        instance_id = str(params["instance_id"][0])
        try:
            operation = self._resolve_operation(instance_id)
        except LookupError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 404)
            return
        if self.headers.get("Prefer", "").strip().lower() == "respond-async":
            json_response(self, {
                "success": True,
                "submitted": True,
                "instance_id": instance_id,
            }, 202)
            self.state.submit_action(operation, f"{self.path} {instance_id}")
            return
        try:
            message = operation()
        except Exception as exc:
            sys.stderr.write(f"[manager] action {self.path} failed: {exc}\n")
            json_response(
                self,
                {"success": False, "error": "manager action failed"},
                409,
            )
            return
        json_response(self, {
            "success": True,
            "instance_id": instance_id,
            "message": message,
        })

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        if self._proxy_service_write(parsed, method="PATCH"):
            return
        self.send_error(404)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if self._proxy_service_write(parsed, method="PUT"):
            return
        self.send_error(404)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if self._proxy_job_request(parsed, method="DELETE"):
            return
        if self._proxy_service_write(parsed, method="DELETE"):
            return
        self.send_error(404)

    def _json_body(self, maximum: int) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > maximum:
            raise ValueError("request body is invalid")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def _login(self) -> None:
        if not self._has_secure_ui_transport():
            json_response(self, {
                "success": False,
                "error": "remote Manager login requires HTTPS outside private LAN",
            }, 400)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 16 * 1024:
            json_response(self, {
                "success": False,
                "error": "invalid login request",
            }, 400)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            token, principal, role = self.state.login(
                str(payload.get("username") or ""),
                str(payload.get("password") or ""),
            )
        except (ValueError, TypeError, json.JSONDecodeError):
            json_response(self, {
                "success": False,
                "error": "invalid login request",
            }, 400)
            return
        except PermissionError as exc:
            json_response(self, {
                "success": False,
                "error": str(exc),
            }, 403)
            return
        except Exception as exc:
            sys.stderr.write(f"[manager] login failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "manager login failed",
            }, 500)
            return
        json_response(self, {
            "success": True,
            "username": principal,
            "role": role,
            "capabilities": {
                "manager": role == "super_admin",
                "research": True,
            },
            "token": token,
            "expires_in": 12 * 60 * 60,
        }, headers={"Set-Cookie": self._session_cookie(token)})

    @staticmethod
    def _session_cookie(token: str, *, clear: bool = False) -> str:
        if clear:
            return "ft-manager-session=; Max-Age=0; HttpOnly; SameSite=Lax; Path=/"
        return f"ft-manager-session={token}; Max-Age={12 * 60 * 60}; HttpOnly; SameSite=Lax; Path=/"

    def _register(self) -> None:
        if not self._has_secure_ui_transport():
            json_response(self, {"success": False, "error": "remote Manager registration requires HTTPS outside private LAN"}, 400)
            return
        try:
            payload = self._json_body(16 * 1024)
            principal, role, alias, organization_id = self.state.register(
                str(payload.get("username") or payload.get("alias") or ""),
                str(payload.get("password") or ""),
                str(payload.get("organization_id") or ""),
            )
            token = self.state.login(principal, str(payload.get("password") or ""))[0]
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return
        json_response(
            self,
            {"success": True, "token": token, "username": principal, "alias": alias, "role": role, "organization_id": organization_id, "capabilities": {"manager": role == "super_admin", "research": True}},
            headers={"Set-Cookie": self._session_cookie(token)},
        )

    def _resolve_operation(self, instance_id: str):
        if self.path == "/vibe/start":
            if instance_id != "service-vibe-trading":
                raise LookupError("managed instance not found")
            return self.state.start_vibe
        if self.path == "/vibe/stop":
            if instance_id != "service-vibe-trading":
                raise LookupError("managed instance not found")
            return self.state.stop_vibe
        worktree = self.state.worktree_for_instance(instance_id)
        if worktree is None:
            raise LookupError("managed instance not found")
        if self.path == "/start":
            return lambda: self.state.start(worktree.path, worktree.port)
        if self.path == "/stop":
            return lambda: self.state.stop(worktree.path)
        if self.path == "/restart-api":
            return lambda: self.state.restart_api(worktree.path, worktree.port)
        if self.path == "/restart-bundle":
            return lambda: self.state.restart_bundle(worktree.path, worktree.port)
        return lambda: self.state.stop(worktree.path, force=True)

    def _serve_client_release(self, path: str) -> bool:
        public_key = (
            Path(__file__).resolve().parents[1]
            / "tools/cli/release/trusted-beta-release-public.pem"
        )
        try:
            if path == "/api/client/releases/beta.json":
                raw, etag = load_client_release_channel(
                    self.state.release_root, "beta", public_key=public_key,
                )
                self._release_bytes(raw, "application/json", etag)
                return True
            if path == "/api/client/releases/beta.xml":
                raw, etag = load_beta_sparkle_appcast(
                    self.state.release_root, public_key=public_key,
                )
                self._release_bytes(raw, "application/rss+xml", etag)
                return True
            match = re.fullmatch(
                r"/api/client/releases/assets/beta/([0-9a-f]{64})\.(dmg|delta)",
                path,
            )
            if match:
                self._release_asset(match.group(1), match.group(2))
                return True
        except FileNotFoundError:
            json_response(self, {"success": False, "error": "release not found"}, 404)
            return True
        except (OSError, ValueError):
            json_response(self, {"success": False, "error": "release unavailable"}, 503)
            return True
        return False

    def _release_bytes(self, raw: bytes, content_type: str, etag: str) -> None:
        if self.headers.get("If-None-Match", "").strip('"') == etag:
            self.send_response(304)
            self.send_header("ETag", f'"{etag}"')
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("ETag", f'"{etag}"')
        self.send_header("Cache-Control", "public, max-age=60")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def _release_asset(self, digest: str, suffix: str) -> None:
        asset = self.state.release_root / "assets/beta" / f"{digest}.{suffix}"
        resolved = asset.resolve(strict=True)
        expected_parent = (self.state.release_root / "assets/beta").resolve()
        if resolved.parent != expected_parent or not resolved.is_file():
            raise FileNotFoundError(asset)
        hasher = hashlib.sha256()
        with resolved.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                hasher.update(chunk)
        if hasher.hexdigest() != digest:
            raise ValueError("release asset digest mismatch")
        size = resolved.stat().st_size
        start, end, status = 0, size - 1, 200
        header = self.headers.get("Range", "")
        if header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
            if not match or (not match.group(1) and not match.group(2)):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2) or end)
            else:
                length = int(match.group(2))
                start = max(0, size - length)
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            end = min(end, size - 1)
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("ETag", f'"{digest}"')
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with resolved.open("rb") as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("[manager] " + (fmt % args) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7998)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument(
        "--data-root",
        default="",
        help="Persistent FactorTester data root (defaults to ../FactorTester)",
    )
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    Handler.state = ManagerState(
        Path(args.repo), args.python,
        Path(args.data_root) if args.data_root else None,
    )
    removed = Handler.state.cleanup_detached_worktrees()
    if removed:
        print(f"Removed {len(removed)} detached worktree(s)")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://localhost:{args.port}/"
    print(f"Worktree Flask manager running at {url}")
    try:
        lan_ip = socket.gethostbyname(socket.gethostname())
        if lan_ip and not lan_ip.startswith("127."):
            print(f"  局域网访问: http://{lan_ip}:{args.port}/")
    except Exception:
        pass
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        Handler.state.stop_all()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
