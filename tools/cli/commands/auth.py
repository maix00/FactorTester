"""Authentication and server configuration commands."""

from __future__ import annotations

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.display import print_home_welcome
from tools.cli.core.errors import friendly_errors
from tools.cli.http import ClientConfig, HttpClientError, load_config, save_config
from tools.cli.state import load_state, save_state


@click.command()
@click.option("--host", default="", help="兼容入口主机；推荐直接使用客户端选择的服务器。")
@click.option("--port", default=None, type=int, help="显式入口端口；不再默认猜测业务端口。")
@click.option("--base-url", default="", help="完整服务地址；提供时忽略 host/port。")
@click.option("--server-id", default="", help="从当前服务器提供的目录选择服务器身份，无需填写业务端口。")
@friendly_errors
def configure(host: str, port: int | None, base_url: str, server_id: str) -> None:
    """Save remote server address for later commands."""
    try:
        previous = load_config().base_url
    except FileNotFoundError:
        previous = ''
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
    if previous != config.base_url:
        # Workspace references belong to their issuing Manager. Credentials
        # are stored per origin and are never copied to the selected target.
        state = load_state()
        state.reset()
        state.workspace_id = ''
        state.configuration_revision = 0
        save_state(state)
    click.echo(f"已配置 TradeResearch 服务: {config.base_url}")


@click.command()
@click.option('--no-browser', is_flag=True, help='Display the Keycloak verification link without opening it.')
@friendly_errors
def login(no_browser: bool = False) -> None:
    """Sign in through Keycloak, or verify an existing endpoint session."""
    from tools.cli.agent_auth import load_capability
    from tools.cli.oidc_device import DeviceLoginError, login as device_login
    if load_capability() is not None:
        raise click.ClickException("Profile 助手能力不能用作用户登录会话")
    try:
        data = client_from_config(persist_cookies=True).current_principal()
    except HttpClientError as exc:
        if exc.status != 401:
            raise
        data = device_login(load_config().base_url, open_browser=not no_browser,
                            show=lambda url, code: click.echo(f'{url}\n{code}', err=True))
    except DeviceLoginError:
        data = device_login(load_config().base_url, open_browser=not no_browser,
                            show=lambda url, code: click.echo(f'{url}\n{code}', err=True))
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
