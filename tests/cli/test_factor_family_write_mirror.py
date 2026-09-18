"""family-write 的镜像规则：只写合法工作区，不一致时告警，入库失败不入工作区。"""

from __future__ import annotations

import os

import pytest

from tools.cli.modules.custom_factors import controller
from tools.data.factor_workspace import storage as workspace_storage

SOURCE = "class ProbeMirror(FactorFamily):\n    value = 1\n"
OLD = "class ProbeMirror(FactorFamily):\n    value = 0\n"


@pytest.fixture()
def fake_root(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace_storage, "existing_factor_workspace_root", lambda username: str(tmp_path))
    return tmp_path


def test_no_configured_workspace_means_no_file(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace_storage, "existing_factor_workspace_root", lambda username: None)
    result = controller.mirror_family_source_to_workspace("u", "ProbeMirror", SOURCE)
    assert result["mirrored"] is False
    assert "未显式配置" in result["reason"]
    assert not (tmp_path / "custom_factors").exists()


def test_mirrors_into_the_configured_workspace(fake_root):
    result = controller.mirror_family_source_to_workspace("u", "ProbeMirror", SOURCE)
    assert result["mirrored"] is True
    target = fake_root / "custom_factors" / "ProbeMirror.py"
    assert target.read_text(encoding="utf-8") == SOURCE
    assert result["overwrote_divergent"] is False


def test_keeps_the_stored_source_and_warns_when_the_workspace_diverged(fake_root):
    target = fake_root / "custom_factors" / "ProbeMirror.py"
    os.makedirs(target.parent, exist_ok=True)
    target.write_text(OLD, encoding="utf-8")
    result = controller.mirror_family_source_to_workspace("u", "ProbeMirror", SOURCE)
    assert result["overwrote_divergent"] is True
    assert target.read_text(encoding="utf-8") == SOURCE
    assert "workspace user download" in result["refresh_hint"]


def test_print_reports_every_step(capsys):
    controller._print_family_write(
        {
            "factor_id": "ProbeMirror",
            "stored": True,
            "mirror": {"mirrored": True, "path": "/w/custom_factors/ProbeMirror.py",
                       "workspace_root": "/w", "overwrote_divergent": True,
                       "refresh_hint": "factortester factor-library workspace user download"},
        }
    )
    out = capsys.readouterr().out
    assert "入库: ProbeMirror（成功）" in out
    assert "工作区镜像: /w/custom_factors/ProbeMirror.py" in out
    assert "原有同名文件内容不同" in out


def test_print_explains_a_failed_store(capsys):
    controller._print_family_write({"factor_id": "X", "stored": False, "stored_error": "boom"})
    out = capsys.readouterr().out
    assert "未写入" in out
    assert "原因: boom" in out


def test_print_explains_a_skipped_mirror(capsys):
    controller._print_family_write(
        {"factor_id": "X", "stored": True, "mirror": {"mirrored": False, "reason": "未显式配置工作区（默认目录不镜像）"}}
    )
    out = capsys.readouterr().out
    assert "工作区镜像: 未写入" in out
    assert "未显式配置工作区" in out
