"""Manager-backed activation required by a source-coupled client release."""

from __future__ import annotations

from dataclasses import dataclass

from tools.cli.manager.client import ManagerClient
from tools.cli.manager.config import (
    ManagerCredentialStore,
    load_manager_config,
)


@dataclass(frozen=True)
class ServiceRestartReceipt:
    manager_url: str
    port: int
    instance_id: str
    action: str
    message: str


def restart_release_service(*, port: int) -> ServiceRestartReceipt:
    """Restart exactly one Manager-owned service bundle by its port.

    A release must never guess a service instance from a branch label: ports
    are the public deployment identity and Manager remains the authority for
    the opaque instance id and drain-aware restart.
    """
    config = load_manager_config()
    token = ManagerCredentialStore(config).read()
    client = ManagerClient(config, token=token, timeout=180)
    worktrees = client.instances().get("worktrees") or []
    matches = [
        item for item in worktrees
        if isinstance(item, dict) and int(item.get("port") or 0) == port
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Manager 未找到唯一的服务端口 {port}；请先通过 "
            "factortester manager list 确认部署"
        )
    target = matches[0]
    instance_id = str(target.get("instance_id") or "").strip()
    if not instance_id:
        raise RuntimeError(f"Manager 返回的端口 {port} 缺少 instance_id")
    response = client.action(instance_id, "restart-all")
    if not response.get("success", True):
        raise RuntimeError("Manager 未接受服务重启")
    return ServiceRestartReceipt(
        manager_url=config.base_url,
        port=port,
        instance_id=instance_id,
        action="restart-bundle",
        message=str(response.get("message") or "重启完成"),
    )
