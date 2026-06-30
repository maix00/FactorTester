from __future__ import annotations

from typing import ClassVar

from tools.testers.backtest.modules.base import ExecutableModule, FieldDefinition, FieldRef


class _ModuleA(ExecutableModule):
    x: ClassVar[FieldRef[int]] = FieldRef("x")


class _ModuleB(ExecutableModule):
    x: ClassVar[FieldRef[int]] = FieldRef("x")


def test_owner_autofilled_per_subclass():
    assert _ModuleA.x.owner == "_ModuleA"
    assert _ModuleB.x.owner == "_ModuleB"


def test_qualified_name_format():
    assert _ModuleA.x.qualified_name == "_ModuleA.x"
    assert repr(_ModuleA.x) == "_ModuleA.x"


def test_fieldref_equality_and_hash():
    assert _ModuleA.x != _ModuleB.x  # different owners
    assert _ModuleA.x == FieldRef("x", owner="_ModuleA")
    assert hash(_ModuleA.x) == hash(FieldRef("x", owner="_ModuleA"))


def test_field_definition_defaults():
    fd = FieldDefinition()
    assert fd.public is False
    assert fd.visible_when is None
    assert fd.editable_when is None
    assert fd.default_when is None
    assert fd.options == ()
