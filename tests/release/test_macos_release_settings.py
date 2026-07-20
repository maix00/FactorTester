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


def test_macos_embeds_signed_local_adapter_web_ui() -> None:
    adapter_root = SOURCES / "Features" / "Adapters"
    controller = (adapter_root / "ClientAdapterController.swift").read_text(
        encoding="utf-8"
    )
    model = (adapter_root / "ClientAdapterModel.swift").read_text(
        encoding="utf-8"
    )
    panel = (adapter_root / "ClientAdapterPanel.swift").read_text(
        encoding="utf-8"
    )
    local_web = (adapter_root / "LocalAdapterWebView.swift").read_text(
        encoding="utf-8"
    )
    web = (SOURCES / "Features" / "Web" / "WebPageView.swift").read_text(
        encoding="utf-8"
    )

    assert '["client"] + tail' in controller
    assert '["adapter", "start", adapter.id]' in controller
    assert "127.0.0.1" in model and "localhost" in model
    assert "openTarget" in panel
    assert "LocalAdapterWebView" in panel
    assert "WebViewRepresentable" in local_web
    assert "syncServerCookies: false" in local_web
    assert "let url: URL" in web
    assert "7899" not in controller + panel + local_web
    for path in sorted(adapter_root.glob("*.swift")):
        subprocess.run(
            ["swiftc", "-frontend", "-parse", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )


def test_macos_manages_provider_neutral_local_profiles() -> None:
    profile_root = SOURCES / "Features" / "Profiles"
    controller = (profile_root / "LocalProfileController.swift").read_text(
        encoding="utf-8"
    )
    settings = (
        SOURCES / "Features" / "Settings" / "ClientReleaseSettingsView.swift"
    ).read_text(encoding="utf-8")
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(profile_root.glob("*.swift"))
    )

    assert '["client", "profile", "list"]' in controller
    assert '"profile", "agent", "set"' in controller
    assert "LocalProfilesView()" in settings
    assert "审批" not in combined
    for forbidden in ("Codex", "model_id", "runtime_id", "password", "token"):
        assert forbidden not in combined
    for path in sorted(profile_root.glob("*.swift")):
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 130
        subprocess.run(
            ["swiftc", "-frontend", "-parse", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )


def test_macos_adapter_secrets_go_to_keychain_not_cli_arguments() -> None:
    profile_root = SOURCES / "Features" / "Profiles"
    form = (profile_root / "LocalAdapterProfileForm.swift").read_text(
        encoding="utf-8"
    )
    controller = (profile_root / "LocalProfileController.swift").read_text(
        encoding="utf-8"
    )
    keychain = (SOURCES / "Services" / "KeychainStore.swift").read_text(
        encoding="utf-8"
    )

    assert "SecureField" in form
    assert "KeychainStore.save" in form
    assert "keychain://" in form
    assert '"--credential-ref"' in controller
    assert "secret" not in controller.lower()
    assert "kSecClassGenericPassword" in keychain
    assert "UserDefaults" not in keychain
    adapter_controller = (
        SOURCES / "Features" / "Adapters" / "ClientAdapterController.swift"
    ).read_text(encoding="utf-8")
    profiles = (
        SOURCES / "Features" / "Profiles" / "LocalProfilesView.swift"
    ).read_text(encoding="utf-8")
    assert '"--profile-id"' in adapter_controller
    assert "client.profile.activeID" in adapter_controller
    assert "用于本地 Adapter" in profiles
