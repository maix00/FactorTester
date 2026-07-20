from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "apple" / "Sources"


def test_macos_settings_use_the_same_deterministic_client_cli() -> None:
    controller = (
        SOURCES / "Features" / "Settings" / "ClientReleaseController.swift"
    ).read_text(encoding="utf-8")
    command = (
        SOURCES / "Features" / "Settings" / "ClientReleaseCommand.swift"
    ).read_text(encoding="utf-8")
    view = (
        SOURCES / "Features" / "Settings" / "ClientReleaseSettingsView.swift"
    ).read_text(encoding="utf-8")
    status = (
        SOURCES / "Features" / "Settings" / "ClientReleaseStatusCard.swift"
    ).read_text(encoding="utf-8")
    home = (
        SOURCES / "Features" / "Home" / "HomeView.swift"
    ).read_text(encoding="utf-8")

    assert 'static let cliPath = "client.release.cliPath"' in controller
    assert 'process.arguments = [executable] + arguments' in command
    for command in ("bootstrap", "update", "status", "rollback"):
        assert f'"{command}"' in controller
    for label in ("当前版本", "可用版本", "运行状态"):
        assert label in status
    for label in ("安装来源", "选择发布 Profile", "首次安装"):
        assert label in view
    assert "密码、token 与审批不会由此界面保存" in view
    assert "客户端设置…" in home
    assert "approval" not in view.lower()


def test_apple_project_generation_and_new_swift_syntax(tmp_path: Path) -> None:
    subprocess.run(
        [
            "xcodegen",
            "generate",
            "--spec",
            str(ROOT / "apple" / "project.yml"),
            "--project",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    for filename in (
        "ClientReleaseCommand.swift",
        "ClientReleaseController.swift",
        "ClientReleaseSettingsView.swift",
        "ClientReleaseStatusCard.swift",
    ):
        subprocess.run(
            [
                "swiftc",
                "-frontend",
                "-parse",
                str(SOURCES / "Features" / "Settings" / filename),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
