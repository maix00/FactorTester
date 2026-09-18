"""worker/守护进程在没有 HTTP 请求上下文时解析因子不得抛 RuntimeError。

背景：提交后由 planning runner / job daemon 展开冻结配置，那里没有请求在飞。
早期实现直接读 Flask session，抛 ``RuntimeError: Working outside of request context``，
把提交请求打断成客户端侧 RemoteDisconnected（实测 POST /run submit 断连）。
"""

import pytest

from server.modules.shared import factor_param_resolver as resolver


def test_request_username_is_empty_without_request_context():
    assert resolver._request_username() == ''


def test_find_visible_factor_does_not_touch_flask_session_outside_request(monkeypatch):
    """无请求上下文时必须走窄路径，不得触碰 Flask session。"""
    calls = []

    def _no_session():
        raise AssertionError('无请求上下文时不得读取 Flask session')

    monkeypatch.setattr(resolver, 'current_user', _no_session)

    class _Instance:
        def factor_from_alias(self, alias):
            calls.append(alias)
            return type('F', (), {'alias': alias})()

        def parse_alias(self, alias):
            return {}

    monkeypatch.setattr(resolver, 'get_factor_family_instance',
                        lambda family, username=None: _Instance())

    item = resolver._find_visible_factor('SomeFamily|N:[10d]')

    assert calls == ['SomeFamily|N:[10d]']          # 走了窄路径
    assert item['factor_family_alias'] == 'SomeFamily'
    assert item['factor_alias'] == 'SomeFamily|N:[10d]'


def test_find_visible_factor_surfaces_a_domain_error_not_a_crash(monkeypatch):
    """家族拿不到（例如用户私有家族且无身份）时给领域错误，而不是 Flask 崩溃。"""
    def _boom(*args, **kwargs):
        raise ImportError("Cannot load factor 'SomeFamily'")

    monkeypatch.setattr(resolver, 'get_factor_family_instance', _boom)

    with pytest.raises(ValueError, match='找不到且无法唯一解析因子'):
        resolver._find_visible_factor('SomeFamily|N:[10d]')


def test_resolve_factor_param_value_alias_branch_has_no_request_context(monkeypatch):
    """端到端：alias 形式的 FactorParam 在无请求上下文时也要给出领域错误。"""
    monkeypatch.setattr(resolver, 'current_user',
                        lambda: (_ for _ in ()).throw(AssertionError('不得读 session')))

    with pytest.raises(ValueError):
        resolver.resolve_factor_param_value('SomeFamily|N:[10d]')
