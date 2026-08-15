"""Reusable Manager restart for the controlled service fleet.

The release gate and server maintenance use the same transaction: capture the
Manager-owned running set, stop only that set, restart the Manager from an
explicit source worktree, and restore the captured instances after health
checks.  Keeping this operation here prevents the release path and the
maintenance CLI from drifting apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from collections.abc import Callable
from collections.abc import Mapping

from tools.cli.manager.client import ManagerClient
from tools.cli.manager.source import resolve_manager_source


@dataclass(frozen=True)
class FleetRestartReceipt:
    manager_url: str
    action: str
    message: str
    restarted_ports: tuple[int, ...] = ()
    restarted_instances: tuple[str, ...] = ()
    source_mode: str = "worktree"
    source_root: str = ""
    source_revision: str = ""
    stop_mode: str = "wait"
    port_stop_modes: tuple[str, ...] = ()


def restart_managed_fleet(
    *,
    client: ManagerClient,
    source_root: Path,
    required_port: int | None = None,
    source_mode: str = "worktree",
    source_revision: str = "",
    stop_mode: str = "wait",
    port_stop_modes: Mapping[int, str] | None = None,
    manager_url: str = "",
    manager_restart: Callable[..., dict] | None = None,
) -> FleetRestartReceipt:
    """Restart Manager and restore every service that was running before it.

    ``required_port`` is an optional release invariant.  When provided, the
    port must be a unique Manager instance and already running; the operation
    still restarts the complete captured fleet.  No previously stopped service
    is started as a side effect.
    """
    session = client.session()
    if not bool((session.get("capabilities") or {}).get("manager")):
        raise RuntimeError("需要有效的 Manager 管理员登录")

    # Resolve and verify the source before stopping anything.  In git-commit
    # mode this creates or reuses an immutable detached checkout, so the
    # running fleet is never left down because the source was ambiguous.
    resolved_source = resolve_manager_source(
        source_root,
        source_mode=source_mode,
        source_revision=source_revision,
    )
    if stop_mode not in {"wait", "force"}:
        raise ValueError("stop mode must be wait or force")
    selected_stop_modes = {
        int(port): str(mode)
        for port, mode in (port_stop_modes or {}).items()
    }
    if any(mode not in {"wait", "force"}
           for mode in selected_stop_modes.values()):
        raise ValueError("per-port stop mode must be wait or force")

    snapshot = client.instances()
    initial = _worktrees_from(snapshot)
    target = _unique_port(initial, required_port) if required_port else None
    occupied = tuple(
        sorted(
            (item for item in initial
             if bool(item.get("port_in_use")) and not _service_active(item)),
            key=lambda item: int(item.get("port") or 0),
        )
    )
    if occupied:
        ports = "、".join(str(int(item.get("port") or 0)) for item in occupied)
        raise RuntimeError(
            f"服务端口 {ports} 被 Manager 外部进程占用；请先停止该进程"
        )

    running = tuple(
        sorted((item for item in initial if _service_active(item)),
               key=lambda item: int(item.get("port") or 0))
    )
    running_ports = {int(item.get("port") or 0) for item in running}
    unknown_stop_ports = set(selected_stop_modes) - running_ports
    if unknown_stop_ports:
        ports = "、".join(str(port) for port in sorted(unknown_stop_ports))
        raise RuntimeError(f"特殊关闭指令指向未运行的服务端口: {ports}")
    if target is not None and not any(
        _instance_id(item) == _instance_id(target) for item in running
    ):
        raise RuntimeError(f"服务端口 {required_port} 当前未开启，无法执行整组重启")

    stopped: list[dict] = []
    try:
        for item in running:
            port = int(item.get("port") or 0)
            mode = selected_stop_modes.get(port, stop_mode)
            action = "force-stop" if mode == "force" else "stop"
            _accepted(client.action(_instance_id(item), action), "关闭服务")
            stopped.append(item)
        _wait_for_ports(client, running, running=False)

        restart = manager_restart or _default_manager_restart
        restart(source_root=resolved_source)
        _wait_for_manager(client)

        restored = tuple(_same_instance(_worktrees(client), item) for item in running)
        for item in restored:
            _accepted(client.action(_instance_id(item), "start"), "恢复服务")
        _wait_for_ports(client, restored, running=True)
    except Exception:
        _restore_after_failure(client, stopped)
        raise

    ports = tuple(int(item["port"]) for item in running)
    instances = tuple(_instance_id(item) for item in running)
    manager_url = manager_url or str(
        getattr(getattr(client, "config", None), "base_url", "") or ""
    )
    return FleetRestartReceipt(
        manager_url=manager_url,
        action="restart-manager-and-services",
        message="Manager 已重启，并恢复端口 " + "、".join(str(port) for port in ports),
        restarted_ports=ports,
        restarted_instances=instances,
        source_mode=source_mode,
        source_root=str(resolved_source.expanduser().resolve()),
        source_revision=source_revision,
        stop_mode=stop_mode,
        port_stop_modes=tuple(
            f"{port}={selected_stop_modes[port]}"
            for port in sorted(selected_stop_modes)
        ),
    )


def _default_manager_restart(*, source_root: Path) -> dict:
    # Import lazily so the reusable Manager module does not import the release
    # command group during normal CLI startup.
    from tools.cli.release.manager_process import restart_manager_process

    return restart_manager_process(source_root=source_root)


def _worktrees(client: ManagerClient) -> list[dict]:
    return _worktrees_from(client.instances())


def _worktrees_from(snapshot: dict) -> list[dict]:
    return [item for item in (snapshot.get("worktrees") or [])
            if isinstance(item, dict)]


def _unique_port(worktrees: list[dict], port: int) -> dict:
    matches = [item for item in worktrees if int(item.get("port") or 0) == port]
    if len(matches) != 1:
        raise RuntimeError(
            f"Manager 未找到唯一的服务端口 {port}；请先通过 "
            "factortester-manager list 确认部署"
        )
    return matches[0]


def _instance_id(item: dict) -> str:
    value = str(item.get("instance_id") or "").strip()
    if not value:
        raise RuntimeError("Manager 返回的服务缺少 instance_id")
    return value


def _service_active(item: dict) -> bool:
    # port_in_use can describe an orphan process; only Manager-owned state is
    # considered stoppable and restorable.
    return bool(item.get("running") or item.get("daemon_running"))


def _accepted(value: dict, action: str) -> None:
    if not value.get("success", True):
        raise RuntimeError(f"Manager 未接受{action}")


def _same_instance(worktrees: list[dict], previous: dict) -> dict:
    identity = _instance_id(previous)
    matches = [item for item in worktrees
               if item.get("instance_id") == identity]
    if len(matches) != 1:
        raise RuntimeError(f"Manager 重启后无法解析原服务 {identity}")
    return matches[0]


def _wait_for_manager(client: ManagerClient, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if bool((client.session().get("capabilities") or {}).get("manager")):
                return
        except Exception as exc:  # Manager is expected to be briefly offline.
            last_error = exc
        time.sleep(0.1)
    raise RuntimeError("Manager 重启后未恢复已登录状态") from last_error


def _wait_for_ports(
    client: ManagerClient,
    expected: tuple[dict, ...],
    *,
    running: bool,
    timeout: float = 120,
) -> None:
    if not expected:
        return
    identities = {_instance_id(item) for item in expected}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = {
            _instance_id(item): item
            for item in _worktrees(client)
            if str(item.get("instance_id") or "").strip()
        }
        if all(_service_active(current.get(identity, {})) is running
               for identity in identities):
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
            if not _service_active(item):
                client.action(_instance_id(item), "start")
    except Exception:
        # Preserve the original failure.  The receipt's captured instance list
        # remains the operator's exact recovery target if Manager is offline.
        return
