"""Error presentation policies for CLI command modules."""

from __future__ import annotations

from functools import wraps

import click

from tools.cli.http import HttpClientError


def friendly_errors(func=None, *, expose_server_error_body: bool = False):
    def decorator(command_func):
        @wraps(command_func)
        def wrapper(*args, **kwargs):
            try:
                return command_func(*args, **kwargs)
            except HttpClientError as exc:
                message = http_error_message(exc, expose_body=expose_server_error_body)
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


def backtest_errors(func):
    """Use for commands that execute user code/backtests.

    Auth/navigation commands should hide local Python tracebacks. Backtest
    commands need the server-returned traceback/source text because that is the
    actionable strategy/runtime error, not a CLI implementation leak.
    """
    return friendly_errors(func, expose_server_error_body=True)


def http_error_message(exc: HttpClientError, *, expose_body: bool = False) -> str:
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

