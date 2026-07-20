from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "apple" / "Sources"


def test_macos_settings_use_single_verified_github_dmg() -> None:
    controller = (
        SOURCES / "Features" / "Settings" / "ClientReleaseController.swift"
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

    models = (
        SOURCES / "Features" / "Updates" / "GitHubReleaseModels.swift"
    ).read_text(encoding="utf-8")
    store = (
        SOURCES / "Features" / "Updates" / "AppUpdateStore.swift"
    ).read_text(encoding="utf-8")
    assert "maix00/FactorTester-Client/releases/latest" in controller
    assert 'name == "FactorTester-Client.dmg"' in models
    assert 'hasPrefix("sha256:")' in models
    assert "SHA256()" in store
    assert "prefix(2)" in store
    assert "NSWorkspace.shared.open" in controller
    assert "replaceItemAt" not in controller
    for label in ("当前版本", "可用版本", "运行状态"):
        assert label in status
    for label in ("公开仓库", "客户端更新", "下载、校验并打开 DMG"):
        assert label in view
    assert "客户端与 Profiles…" in home
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
    for path in sorted((SOURCES / "Features" / "Updates").glob("*.swift")):
        subprocess.run(
            ["swiftc", "-frontend", "-parse", str(path)],
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
    tab = (SOURCES / "Navigation" / "ClientTabView.swift").read_text(
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
    assert "!adapter.running && !adapter.healthy" in controller
    assert "外部服务可用" in panel
    assert "127.0.0.1" in model and "localhost" in model
    assert "openTarget" in panel
    assert "LocalAdapterWebView" in tab
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


def test_macos_profiles_show_workspace_ownership_and_folder_picker() -> None:
    profile_root = SOURCES / "Features" / "Profiles"
    model = (profile_root / "LocalProfileModel.swift").read_text(
        encoding="utf-8"
    )
    form = (profile_root / "LocalProfileForm.swift").read_text(
        encoding="utf-8"
    )
    view = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            profile_root / "LocalProfilesView.swift",
            profile_root / "WorkspaceRegistryRow.swift",
        )
    )
    assert 'json["workspaces"]' in model
    assert 'json["owner_ref"]' in model
    assert "allowedContentTypes: [.folder]" in form
    assert "可见工作区" in view
    assert "Owner:" in view


def test_macos_tabs_and_account_center_use_real_routes() -> None:
    navigation = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((SOURCES / "Navigation").glob("ClientTab*.swift"))
    )
    account = (
        SOURCES / "Features" / "Account" / "AccountCenterView.swift"
    ).read_text(encoding="utf-8")
    api = (SOURCES / "Networking" / "APIClient.swift").read_text(
        encoding="utf-8"
    )
    config = (SOURCES / "Config" / "ServerConfig.swift").read_text(
        encoding="utf-8"
    )

    assert "返回主页" in navigation
    assert "case web(path: String)" in navigation
    assert "/api/account/password" in api
    assert "/products" in account
    assert "/custom-factors/editor" in account
    assert '"127.0.0.1"' in config
    assert '"8000"' in config
