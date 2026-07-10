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
@friendly_errors
def login(username: str, password: str) -> None:
    """Login through the configured remote server."""
    if not password:
        password = getpass.getpass("Password: ")
    data = client_from_config().login(username, password)
    click.echo(f"已登录: {data.get('username') or username}")
    page = client_from_config().bootstrap_page()
    state = load_state()
    state.reset()
    state.page_uuid = str(page.get("page_uuid") or "")
    save_state(state)
    if state.page_uuid:
        click.echo(f"页面上下文: {state.page_uuid}")
    print_home_welcome()
