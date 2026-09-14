"""Authentication and server configuration commands."""

from __future__ import annotations

import getpass

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
    click.echo(f"已配置 FactorTester 服务: {config.base_url}")


@click.command()
@click.option("--username", default="", help="已有客户端会话时无需重复输入账号。")
@click.option("--password", default="", help="不传则安全提示输入。")
@click.option(
    "--keep-login/--no-keep-login",
    default=True,
    show_default=True,
    help="持久保存本地 session；默认跳过十分钟空闲退出，服务端最长保留三十天。",
)
@friendly_errors
def login(username: str, password: str, keep_login: bool) -> None:
    """Login through the configured remote server."""
    client = client_from_config(persist_cookies=keep_login)
    if client.session.bearer_token and client.session.agent_capability is None:
        data = client.current_principal()
        observed = str(data.get("username") or "")
        if username and username not in {observed, str(data.get("alias") or "")}:
            raise ValueError("当前客户端已登录其他身份；请先在客户端切换账号")
        click.echo(f"已使用客户端认证会话: {observed}")
        return
    if not username:
        username = click.prompt("Username")
    if not password:
        password = getpass.getpass("Password: ")
    data = client.login(username, password)
    click.echo(
        f"已登录: {data.get('username') or username} "
        f"keep_login={str(keep_login).lower()}"
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
