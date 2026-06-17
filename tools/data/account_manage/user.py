from __future__ import annotations

from typing import TYPE_CHECKING, List

from tools.data.types import UniqueNameObject

if TYPE_CHECKING:
    from tools.factors.FactorTester import FactorTester


class User(UniqueNameObject):
    """
    系统用户。

    属性：
        name      (str)      : 全名，格式 {username}@{serial}，如 '张三@1'
        alias     (str)      : 原始用户名，如 '张三'（用于展示）
        serial    (int)      : 序列号，从 1 开始
        is_admin  (bool)     : 是否为管理员
        testers   (list)     : 该用户创建的 FactorTester 列表
    """

    def __init__(self, name: str, is_admin: bool = False, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            parts = name.rsplit('@', 1)
            if len(parts) == 2 and parts[1].isdigit():
                alias = parts[0]
                self.serial = int(parts[1])
            else:
                alias = name
                self.serial = 1
            super().__init__(name=name, alias=alias, desc=f'用户 {alias}', *args, **kwargs)
            self.is_admin = is_admin
            self._testers: 'List[FactorTester]' = []

    @property
    def testers(self) -> 'List[FactorTester]':
        return [t for t in self._testers if t is not None]

    def add_tester(self, tester: 'FactorTester') -> None:
        if tester not in self._testers:
            self._testers.append(tester)

    def remove_tester(self, tester: 'FactorTester') -> None:
        self._testers = [t for t in self._testers if t is not None and t is not tester]

    def cleanup_testers(self) -> None:
        """退出登录时清理该用户的所有 FactorTester。"""
        for tester in self.testers:
            try:
                tester.delete()
            except Exception:
                pass
        self._testers.clear()
