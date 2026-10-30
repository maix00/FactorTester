"""Authentication and server configuration commands."""

from __future__ import annotations

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.display import print_home_welcome
from tools.cli.core.errors import friendly_errors
from tools.cli.http import ClientConfig, save_config, load_config
from tools.cli.state import load_state, save_state


@click.command()
@click.option("--host", default="", help="兼容入口主机；推荐直接使用客户端选择的服务器。")
@click.option("--port", default=None, type=int, help="显式入口端口；不再默认猜测业务端口。")
@click.option("--base-url", default="", help="完整服务地址；提供时忽略 host/port。")
@click.option("--server-id", default="", help="从当前服务器提供的目录选择服务器身份，无需填写业务端口。")
@friendly_errors
def configure(host: str, port: int | None, base_url: str, server_id: str) -> None:
    """Save remote server address for later commands."""
    if base_url:
        config = ClientConfig(base_url=base_url.rstrip("/"))
    elif host:
        config = ClientConfig.from_host_port(host, port) if port is not None else ClientConfig(
            host.rstrip("/") if "://" in host else "https://" + host)
    elif port is not None:
        raise ValueError("--port requires an explicit --host")
    else:
        config = load_config()  # Native client publishes the selected Manager connection.
    if server_id:
        from tools.cli.server_connection import discover_server
        config = discover_server(config, server_id)
    save_config(config)
    click.echo(f"已配置 TradeResearch 服务: {config.base_url}")


@click.command()
@friendly_errors
def login() -> None:
    """Verify the existing Keycloak-backed desktop/web session for this Manager."""
    client = client_from_config(persist_cookies=True)
    if client.session.agent_capability is not None:
        raise click.ClickException("Profile 助手能力不能用作用户登录会话")
    try:
        data = client.current_principal()
    except Exception as exc:
        raise click.ClickException(
            "CLI 不再收集本地密码。请先在 TradeResearch 网页或桌面端通过 Keycloak 登录，"
            "再运行 traderesearch login 验证当前服务器会话。"
        ) from exc
    observed = str(data.get("username") or "").strip()
    if not observed:
        raise click.ClickException("当前服务器没有返回已验证的 Keycloak 用户身份")
    click.echo(
        f"已验证 TradeResearch Keycloak 会话: {observed}"
    )
    state = load_state()
    state.reset()
    state.workspace_id = ""
    state.configuration_revision = 0
    save_state(state)
    print_home_welcome()


@click.command()
@friendly_errors
def logout() -> None:
    """Logout remotely and remove the persisted local session cookie."""
    client_from_config().logout()
    state = load_state()
    state.reset()
    save_state(state)
    click.echo("已登出，并清除本地登录状态。")
