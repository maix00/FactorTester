"""工作区上传的可观测性：被跳过时必须说明原因，而不是只报「更新 0」。"""

from __future__ import annotations

from tools.cli.modules.custom_factors.controller import _print_workspace_action


def test_skipped_upload_explains_why(capsys):
    _print_workspace_action(
        "上传入库",
        {
            "workspace_root": "/data/users/u/personal-workspace/factor-library",
            "git_selected_branch": "download",
            "current_branch": "download",
            "auto_sync_branch": "upload",
            "skipped": True,
            "skip_reason": "当前分支 download 不是自动同步分支 upload",
            "updated_custom_count": 0,
            "updated_public_count": 0,
        },
    )
    out = capsys.readouterr().out
    assert "跳过" in out
    assert "当前分支 download 不是自动同步分支 upload" in out
    assert "分支判定: 当前=download 自动同步=upload" in out
    assert "更新自定义因子: 0" in out


def test_normal_upload_has_no_skip_noise(capsys):
    _print_workspace_action(
        "上传入库",
        {
            "workspace_root": "/data/users/u/personal-workspace/factor-library",
            "git_selected_branch": "upload",
            "updated_custom_count": 3,
            "updated_public_count": 0,
        },
    )
    out = capsys.readouterr().out
    assert "跳过" not in out
    assert "更新自定义因子: 3" in out
