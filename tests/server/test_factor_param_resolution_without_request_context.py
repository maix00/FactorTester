"""worker/守护进程在没有 HTTP 请求上下文时解析因子不得抛 RuntimeError。

背景：提交后由 planning runner / job daemon 展开冻结配置，那里没有请求在飞。
早期实现直接读 Flask session，抛 ``RuntimeError: Working outside of request context``，
把提交请求打断成客户端侧 RemoteDisconnected（实测 POST /run submit 断连）。

契约（与平台既有测试一致）：没有身份时仍按原来的语义尝试读取身份；读取抛
RuntimeError（无请求上下文）时才退化为「无身份」，并改走按家族解析的窄路径，
最终给出领域错误而不是 Flask 崩溃。其他异常必须继续抛出，不得被吞掉。
"""

import pytest

from server.modules.shared import factor_param_resolver as resolver


def _outside_request_context():
    raise RuntimeError("Working outside of request context.")


def test_request_username_is_empty_when_the_session_is_unavailable(monkeypatch):
    monkeypatch.setattr(resolver, 'current_user', _outside_request_context)

    assert resolver._request_username() == ''


def test_request_username_does_not_swallow_unrelated_errors(monkeypatch):
    """只允许退化为「无身份」这一种情况；其他异常必须继续抛出。"""
    def _boom():
        raise KeyError('unexpected')

    monkeypatch.setattr(resolver, 'current_user', _boom)

    with pytest.raises(KeyError):
        resolver._request_username()


def test_find_visible_factor_degrades_to_a_domain_error_without_a_session(monkeypatch):
    monkeypatch.setattr(resolver, 'current_user', _outside_request_context)

    def _unresolvable(*args, **kwargs):
        raise ImportError("Cannot load factor 'SomeFamily'")

    monkeypatch.setattr(resolver, 'get_factor_family_instance', _unresolvable)

    with pytest.raises(ValueError, match='找不到且无法唯一解析因子'):
        resolver._find_visible_factor('SomeFamily|N:[10d]')


def test_find_visible_factor_resolves_by_family_when_there_is_no_identity(monkeypatch):
    """无身份时走按家族解析的窄路径，而不是构建空总览把可解析因子误报成找不到。"""
    monkeypatch.setattr(resolver, 'current_user', _outside_request_context)

    class _Instance:
        def factor_from_alias(self, alias):
            return type('F', (), {'alias': alias})()

        def parse_alias(self, alias):
            return {}

    monkeypatch.setattr(resolver, 'get_factor_family_instance',
                        lambda family, username=None: _Instance())

    item = resolver._find_visible_factor('SomeFamily|N:[10d]')

    assert item['factor_family_alias'] == 'SomeFamily'
    assert item['factor_alias'] == 'SomeFamily|N:[10d]'


def test_resolve_factor_param_value_alias_branch_never_raises_runtime_error(monkeypatch):
    """端到端：无请求上下文时 alias 形式的 FactorParam 给领域错误，不是 Flask 崩溃。"""
    monkeypatch.setattr(resolver, 'current_user', _outside_request_context)

    with pytest.raises(ValueError):
        resolver.resolve_factor_param_value('SomeFamily|N:[10d]')
