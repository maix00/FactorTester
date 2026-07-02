"""Click entrypoint for the separately installed FactorTester CLI."""

from __future__ import annotations

import getpass
from functools import wraps
from typing import Any

import click

from .client import FactorTesterClient
from .field_store import FieldStore, visible_fields
from .http import ClientConfig, HttpClientError, HttpSession, load_config, save_config
from .state import CliState, load_state, save_state


@click.group()
def cli() -> None:
    """FactorTester remote HTTP client."""


def _friendly_errors(func=None, *, expose_server_error_body: bool = False):
    def decorator(command_func):
        @wraps(command_func)
        def wrapper(*args, **kwargs):
            try:
                return command_func(*args, **kwargs)
            except HttpClientError as exc:
                message = _http_error_message(exc, expose_body=expose_server_error_body)
                raise click.ClickException(message) from None
            except FileNotFoundError as exc:
                raise click.ClickException(str(exc)) from None
            except ValueError as exc:
                raise click.ClickException(str(exc)) from None
            except RuntimeError as exc:
                raise click.ClickException(str(exc)) from None

        return wrapper

    if func is None:
        return decorator
    return decorator(func)


def _http_error_message(exc: HttpClientError, *, expose_body: bool = False) -> str:
    if expose_body or exc.status >= 500:
        body = exc.body.strip()
        return f"请求失败 ({exc.status}):\n{body}" if body else f"请求失败 ({exc.status}): {exc.url}"
    try:
        import json

        payload = json.loads(exc.body)
    except Exception:
        payload = {}
    if isinstance(payload, dict):
        detail = payload.get("error") or payload.get("message")
        if detail:
            return f"请求失败 ({exc.status}): {detail}"
    return f"请求失败 ({exc.status}): {exc.url}"


def _backtest_errors(func):
    """Use for commands that execute user code/backtests.

    Auth/navigation commands should hide local Python tracebacks. Backtest
    commands need the server-returned traceback/source text because that is the
    actionable strategy/runtime error, not a CLI implementation leak.
    """
    return _friendly_errors(func, expose_server_error_body=True)


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8114, show_default=True, type=int)
@click.option("--base-url", default="", help="完整服务地址；提供时忽略 host/port。")
@_friendly_errors
def configure(host: str, port: int, base_url: str) -> None:
    """Save remote server address for later commands."""
    config = ClientConfig(base_url=base_url.rstrip("/")) if base_url else ClientConfig.from_host_port(host, port)
    save_config(config)
    click.echo(f"已配置 FactorTester 服务: {config.base_url}")


@cli.command()
@click.option("--username", prompt=True)
@click.option("--password", default="", help="不传则安全提示输入。")
@_friendly_errors
def login(username: str, password: str) -> None:
    """Login through the configured remote server."""
    if not password:
        password = getpass.getpass("Password: ")
    data = _client_from_config().login(username, password)
    click.echo(f"已登录: {data.get('username') or username}")
    state = load_state()
    state.reset()
    save_state(state)
    _print_home_welcome()


@cli.command("list")
@_friendly_errors
def list_modules() -> None:
    """List the next navigation layer from the current CLI location."""
    state = load_state()
    modules = _client_from_config().list_modules(parent=state.current_parent)
    click.echo(f"当前位置: {state.location_label}")
    for line in _module_lines(modules):
        click.echo(line)
    if state.current_parent is not None:
        click.echo("返回上一层: factortester back")


@cli.command()
@_friendly_errors
def home() -> None:
    """Return to the CLI home location."""
    state = load_state()
    state.reset()
    save_state(state)
    _print_home_welcome()


@cli.command()
@_friendly_errors
def back() -> None:
    """Return to the previous navigation layer."""
    state = load_state()
    state.back()
    save_state(state)
    click.echo(f"已返回: {state.location_label}")


@cli.command("single_factor_family_test")
@click.option("--factor-family", "--factor_family", default="", help="要测试的因子家族。")
@click.argument("path", nargs=-1)
@_friendly_errors
def enter_single_factor_family_test(factor_family: str, path: tuple[str, ...]) -> None:
    """Enter the single-factor-family test page controller."""
    if not factor_family:
        factor_family = click.prompt("因子家族", default="", show_default=False)
    if not factor_family:
        raise click.ClickException("必须选择 factor_family")
    state = load_state()
    _ensure_child_available(state.current_parent, "single_factor_family_test")
    state.enter("single_factor_family_test")
    state.factor_family = factor_family
    for child in path:
        _ensure_child_available(state.current_parent, child)
        state.enter(child)
    save_state(state)
    if path:
        _print_location_welcome(state)
    else:
        _print_single_factor_family_welcome(state)


@cli.command("group_test")
@_friendly_errors
def enter_group_test() -> None:
    """Enter the group backtest controller from the current page."""
    state = load_state()
    _ensure_child_available(state.current_parent, "group_test")
    state.enter("group_test")
    save_state(state)
    _print_group_test_welcome(state)


def _print_group_test_welcome(state: CliState) -> None:
    click.echo("分组回测")
    if state.factor_family:
        click.echo(f"因子家族: {state.factor_family}")
    click.echo("下一步: factortester list 查看分组回测设置 tabs；factortester back 返回。")


@cli.command()
@click.argument("key")
@_friendly_errors
def describe(key: str) -> None:
    """Describe a tester/backtest setting application."""
    client = _client_from_config()
    manifest = client.manifest(key)
    _print_manifest(manifest)


@cli.command()
@click.argument("key")
@_friendly_errors
def edit(key: str) -> None:
    """Interactively edit server-registered setting fields."""
    client = _client_from_config()
    manifest = client.manifest(key)
    store = FieldStore.from_manifest(manifest)
    tab_lists = manifest.get("tab_lists") or {}
    tabs = list(tab_lists.get("local-settings") or [])
    if not tabs:
        tabs = [{"key": meta.get("tab_key"), "label": meta.get("tab_key")} for meta in store.defaults.values()]
    tabs = _dedupe_tabs(tabs)

    while True:
        click.echo()
        click.echo(f"{key} 设置")
        for index, tab in enumerate(tabs, start=1):
            click.echo(f"  {index}. {tab.get('label') or tab.get('key')}")
        choice = click.prompt("选择 tab（q 退出）", default="q", show_default=False)
        if choice.lower() in {"q", "quit", "exit"}:
            break
        tab = _pick(tabs, choice)
        if tab is None:
            click.echo("无效 tab")
            continue
        tab_key = str(tab.get("key") or "")
        tab_manifest = client.tab_manifest(key, tab_key)
        tab_store = FieldStore.from_manifest(tab_manifest, values=store.explicit_values, parent=store.parent)
        fields = visible_fields(tab_store)
        if not fields:
            click.echo("该 tab 没有可编辑字段")
            continue
        for index, (field_key, meta) in enumerate(fields, start=1):
            click.echo(f"  {index}. {meta.get('label') or field_key}: {tab_store.effective(field_key)!r}")
        field_choice = click.prompt("选择字段（q 返回）", default="q", show_default=False)
        if field_choice.lower() in {"q", "quit", "exit"}:
            continue
        picked = _pick(fields, field_choice)
        if picked is None:
            click.echo("无效字段")
            continue
        field_key, meta = picked
        value = _prompt_value(meta, tab_store.effective(field_key))
        store.set(field_key, value)
        click.echo(f"已设置 {meta.get('label') or field_key}: {value}")

    click.echo("当前显式设置:")
    for field_key, value in store.to_payload().items():
        label = store.field(field_key).get("label", field_key)
        click.echo(f"  {label}: {value}")


def _client_from_config() -> FactorTesterClient:
    config = load_config()
    return FactorTesterClient(HttpSession(config.base_url))


def _ensure_child_available(parent: str | None, key: str) -> None:
    modules = _client_from_config().list_modules(parent=parent)
    if any(module.get("key") == key for module in modules):
        return
    location = CliState(current_parent=parent).location_label
    raise RuntimeError(f"当前位置 {location} 下没有 {key}；请先 factortester list 查看可进入项。")


def _print_home_welcome() -> None:
    click.echo("欢迎使用 FactorTester CLI")
    click.echo("常用操作:")
    click.echo("  factortester list                         查看当前层级可进入模块")
    click.echo("  factortester single_factor_family_test    进入单因子家族测试")
    click.echo("  factortester back                         返回上一层")


def _print_single_factor_family_welcome(state: CliState) -> None:
    click.echo("单因子家族测试")
    click.echo(f"已选择 factor_family: {state.factor_family}")
    click.echo("下一步: factortester list 查看测试模块；例如 factortester group_test 进入分组回测。")


def _print_location_welcome(state: CliState) -> None:
    if state.current_parent == "single_factor_family_test":
        _print_single_factor_family_welcome(state)
        return
    if state.current_parent == "group_test":
        _print_group_test_welcome(state)
        return
    click.echo(f"已进入: {state.location_label}")
    click.echo("下一步: factortester list 查看下一层；factortester back 返回。")


def _module_lines(modules: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for module in modules:
        key = module.get("key", "")
        label = module.get("label", key)
        kind = module.get("kind", "module")
        marker = " +" if module.get("has_children") else ""
        lines.append(f"- [{kind}] {key}: {label}{marker}")
    return lines


def _print_manifest(manifest: dict[str, Any]) -> None:
    click.echo(f"应用: {manifest.get('application')}")
    click.echo("Tabs:")
    tab_lists = manifest.get("tab_lists") or {}
    for mount, tabs in tab_lists.items():
        labels = ", ".join(str(tab.get("label") or tab.get("key")) for tab in tabs or [])
        click.echo(f"  {mount}: {labels}")
    click.echo("Settings:")
    store = FieldStore.from_manifest(manifest)
    for field_key, meta in visible_fields(store):
        label = meta.get("label") or field_key
        control = meta.get("control_template") or "unknown"
        click.echo(f"  {field_key} ({label}, {control}) = {store.effective(field_key)!r}")


def _dedupe_tabs(tabs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for tab in tabs:
        key = str(tab.get("key") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(tab)
    return result


def _pick(items: list[Any], choice: str) -> Any | None:
    try:
        index = int(choice)
    except ValueError:
        return None
    if 1 <= index <= len(items):
        return items[index - 1]
    return None


def _prompt_value(meta: dict[str, Any], current: Any) -> Any:
    control = meta.get("control_template")
    options = meta.get("options") or []
    if control == "select" and options:
        for index, option in enumerate(options, start=1):
            click.echo(f"    {index}. {option.get('label') or option.get('value')} [{option.get('value')}]")
        choice = click.prompt("选择值", default="", show_default=False)
        picked = _pick(options, choice)
        if picked is not None:
            return picked.get("value")
        return choice if choice != "" else current
    if control == "number":
        raw = click.prompt("输入数字", default=str(current if current is not None else ""), show_default=False)
        try:
            return int(raw)
        except ValueError:
            return float(raw)
    if control == "boolean":
        return click.confirm("是否启用", default=bool(current))
    return click.prompt("输入值", default=str(current if current is not None else ""), show_default=False)


if __name__ == "__main__":
    cli()
