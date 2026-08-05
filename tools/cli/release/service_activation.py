"""Authenticated Manager and service-fleet restart for client releases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

from tools.cli.manager.client import ManagerClient
from tools.cli.manager.config import ManagerCredentialStore, load_manager_config
from tools.cli.release.manager_process import restart_manager_process


@dataclass(frozen=True)
class ServiceRestartReceipt:
    manager_url: str
    port: int
    instance_id: str
    action: str
    message: str
    restarted_ports: tuple[int, ...] = ()
    release_root: str = ""
    source_root: str = ""
    source_revision: str = ""


def restart_release_service(
    *, port: int, source_root: Path, source_revision: str,
) -> ServiceRestartReceipt:
    """Restart Manager and exactly the service ports running before release.

    The Keychain-backed Manager session is validated before any mutation.  A
    release never starts a previously stopped port, and it never builds while
    an active job prevents a graceful stop or any captured port fails to
    return healthy after the Manager restart.
    """
    config = load_manager_config()
    token = ManagerCredentialStore(config).read()
    client = ManagerClient(config, token=token, timeout=180)
    session = client.session()
    if not bool((session.get("capabilities") or {}).get("manager")):
        raise RuntimeError("发布需要 Keychain 中有效的 Manager 管理员登录")

    snapshot = client.instances()
    initial = _worktrees_from(snapshot)
    manager = snapshot.get("manager") or {}
    release_root = str(manager.get("release_root") or "").strip()
    if not release_root:
        raise RuntimeError("Manager 未声明统一客户端发布目录")
    target = _unique_port(initial, port)
    occupied = tuple(
        sorted(
            (
                item for item in initial
                if bool(item.get("port_in_use")) and not _service_active(item)
            ),
            key=lambda item: int(item.get("port") or 0),
        )
    )
    if occupied:
        ports = "、".join(str(int(item.get("port") or 0)) for item in occupied)
        raise RuntimeError(
            f"服务端口 {ports} 被 Manager 外部进程占用；请先停止该进程后再发布"
        )
    running = tuple(
        sorted(
            (item for item in initial if _is_running(item)),
            key=lambda item: int(item.get("port") or 0),
        )
    )
    if target not in running:
        raise RuntimeError(f"发布服务端口 {port} 当前未开启，无法执行整组重启")

    stopped: list[dict] = []
    try:
        for item in running:
            _accepted(client.action(_instance_id(item), "stop"), "停止服务")
            stopped.append(item)
        _wait_for_ports(client, running, running=False)

        restart_manager_process(source_root=source_root)
        _wait_for_manager(client)

        current = _worktrees(client)
        restored = tuple(
            _same_instance(current, item) for item in running
        )
        for item in restored:
            _accepted(client.action(_instance_id(item), "start"), "恢复服务")
        _wait_for_ports(client, restored, running=True)
    except Exception:
        _restore_after_failure(client, stopped)
        raise

    restarted_ports = tuple(int(item["port"]) for item in running)
    return ServiceRestartReceipt(
        manager_url=config.base_url,
        port=port,
        instance_id=_instance_id(target),
        action="restart-manager-and-services",
        message=(
            "Manager 已重启，并恢复端口 "
            + "、".join(str(value) for value in restarted_ports)
        ),
        restarted_ports=restarted_ports,
        release_root=release_root,
        source_root=str(source_root.resolve()),
        source_revision=source_revision,
    )


def _worktrees(client: ManagerClient) -> list[dict]:
    return _worktrees_from(client.instances())


def _worktrees_from(snapshot: dict) -> list[dict]:
    value = snapshot.get("worktrees") or []
    return [item for item in value if isinstance(item, dict)]


def _unique_port(worktrees: list[dict], port: int) -> dict:
    matches = [item for item in worktrees if int(item.get("port") or 0) == port]
    if len(matches) != 1:
        raise RuntimeError(
            f"Manager 未找到唯一的服务端口 {port}；请先通过 "
            "factortester manager list 确认部署"
        )
    return matches[0]


def _instance_id(item: dict) -> str:
    value = str(item.get("instance_id") or "").strip()
    if not value:
        raise RuntimeError("Manager 返回的服务缺少 instance_id")
    return value


def _is_running(item: dict) -> bool:
    return _service_active(item)


def _service_active(item: dict) -> bool:
    """Whether Manager owns an active service process.

    ``port_in_use`` is deliberately not included: it also reports orphaned
    processes, which cannot be stopped through the Manager instance action.
    Treating those as active makes the stop wait loop impossible to finish.
    """
    return bool(item.get("running") or item.get("daemon_running"))


def _accepted(value: dict, action: str) -> None:
    if not value.get("success", True):
        raise RuntimeError(f"Manager 未接受{action}")


def _same_instance(worktrees: list[dict], previous: dict) -> dict:
    instance_id = _instance_id(previous)
    matches = [item for item in worktrees if item.get("instance_id") == instance_id]
    if len(matches) != 1:
        raise RuntimeError(
            f"Manager 重启后无法解析原服务端口 {previous.get('port')}"
        )
    return matches[0]


def _wait_for_manager(client: ManagerClient, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            session = client.session()
            if bool((session.get("capabilities") or {}).get("manager")):
                return
        except Exception as exc:  # Manager is expected to be briefly offline.
            last_error = exc
        time.sleep(0.1)
    raise RuntimeError("Manager 重启后未恢复已登录状态") from last_error


def _wait_for_ports(
    client: ManagerClient,
    expected: tuple[dict, ...] | list[dict],
    *,
    running: bool,
    timeout: float = 120,
) -> None:
    identities = {_instance_id(item) for item in expected}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = {
            _instance_id(item): item
            for item in _worktrees(client)
            if str(item.get("instance_id") or "").strip()
        }
        states = [
            _is_running(current.get(identity, {}))
            for identity in identities
        ]
        if states and all(state is running for state in states):
            return
        time.sleep(0.1)
    state = "恢复" if running else "关闭"
    raise RuntimeError(f"服务端口未能全部{state}")


def _restore_after_failure(client: ManagerClient, stopped: list[dict]) -> None:
    if not stopped:
        return
    try:
        _wait_for_manager(client, timeout=10)
        current = _worktrees(client)
        for previous in stopped:
            item = _same_instance(current, previous)
            if not _is_running(item):
                client.action(_instance_id(item), "start")
    except Exception:
        # Preserve the original release failure; operators can use the saved
        # port list in Manager to recover manually if Manager itself is down.
        return
