"""Authentication and server configuration commands."""

from __future__ import annotations

import getpass

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.display import print_home_welcome
from tools.cli.core.errors import friendly_errors
from tools.cli.http import ClientConfig, save_config
from tools.cli.state import load_state, save_state


@click.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8114, show_default=True, type=int)
@click.option("--base-url", default="", help="完整服务地址；提供时忽略 host/port。")
@friendly_errors
def configure(host: str, port: int, base_url: str) -> None:
    """Save remote server address for later commands."""
    config = ClientConfig(base_url=base_url.rstrip("/")) if base_url else ClientConfig.from_host_port(host, port)
    save_config(config)
    click.echo(f"已配置 FactorTester 服务: {config.base_url}")


@click.command()
@click.option("--username", prompt=True)
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
    if not password:
        password = getpass.getpass("Password: ")
    client = client_from_config()
    data = client.login(username, password)
    persistence = client.set_keep_login(keep_login)
    click.echo(
        f"已登录: {data.get('username') or username} "
        f"keep_login={str(bool(persistence.get('keep_login'))).lower()}"
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
