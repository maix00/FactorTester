"""Release-specific validation around the reusable Manager fleet restart."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Mapping

from tools.cli.manager.client import ManagerClient
from tools.cli.manager.config import ManagerCredentialStore, load_manager_config
from tools.cli.manager.fleet import restart_managed_fleet
from tools.cli.release.manager_process import restart_manager_process


@dataclass(frozen=True)
class ServiceRestartReceipt:
    manager_url: str
    port: int
    instance_id: str
    action: str
    message: str
    restarted_ports: tuple[int, ...] = ()
    source_mode: str = "worktree"
    release_root: str = ""
    source_root: str = ""
    source_revision: str = ""
    stop_mode: str = "wait"
    port_stop_modes: tuple[str, ...] = ()


def restart_release_service(
    *,
    port: int,
    source_root: Path,
    source_revision: str,
    source_mode: str = "worktree",
    stop_mode: str = "wait",
    port_stop_modes: Mapping[int, str] | None = None,
) -> ServiceRestartReceipt:
    """Validate the release target, then restart the complete managed fleet.

    The stop/restart/restore transaction lives in ``manager.fleet`` and is
    intentionally shared with the maintenance CLI.  Release-only checks such
    as the declared release root and the required target port remain here.
    """
    config = load_manager_config()
    token = ManagerCredentialStore(config).read()
    client = ManagerClient(config, token=token, timeout=180)
    session = client.session()
    if not bool((session.get("capabilities") or {}).get("manager")):
        raise RuntimeError("发布需要 Keychain 中有效的 Manager 管理员登录")
    snapshot = client.instances()
    manager = snapshot.get("manager") or {}
    release_root = str(manager.get("release_root") or "").strip()
    if not release_root:
        raise RuntimeError("Manager 未声明统一客户端发布目录")

    target = _unique_port(snapshot, port)
    receipt = restart_managed_fleet(
        client=client,
        source_root=source_root,
        source_mode=source_mode,
        source_revision=source_revision,
        stop_mode=stop_mode,
        port_stop_modes=port_stop_modes,
        required_port=port,
        manager_url=config.base_url,
        # Keep the release module's patch point for existing release tests and
        # for callers that wrap LaunchAgent restart behavior.
        manager_restart=restart_manager_process,
    )
    return ServiceRestartReceipt(
        manager_url=config.base_url,
        port=port,
        instance_id=_instance_id(target),
        action=receipt.action,
        message=receipt.message,
        restarted_ports=receipt.restarted_ports,
        source_mode=receipt.source_mode,
        release_root=release_root,
        source_root=receipt.source_root,
        source_revision=receipt.source_revision,
        stop_mode=receipt.stop_mode,
        port_stop_modes=receipt.port_stop_modes,
    )


def _unique_port(snapshot: dict, port: int) -> dict:
    matches = [
        item for item in (snapshot.get("worktrees") or [])
        if isinstance(item, dict) and int(item.get("port") or 0) == port
    ]
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
