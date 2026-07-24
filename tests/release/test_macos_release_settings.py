from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "apple" / "Sources"


def test_macos_settings_keep_main_and_beta_on_authoritative_sources() -> None:
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

    store = (
        SOURCES / "Features" / "Updates" / "AppUpdateStore.swift"
    ).read_text(encoding="utf-8")
    resolution = (
        SOURCES / "Features" / "Settings" / "ClientReleaseResolution.swift"
    ).read_text(encoding="utf-8")
    app = (SOURCES / "App" / "FactorTesterClientApp.swift").read_text(
        encoding="utf-8"
    )
    manifest = (
        SOURCES / "Features" / "Updates" / "AppUpdateManifest.swift"
    ).read_text(encoding="utf-8")
    inspector = (
        SOURCES / "Features" / "Updates" / "AppInstallerInspector.swift"
    ).read_text(encoding="utf-8")
    installer = (
        SOURCES / "Features" / "Updates" / "AppUpdateInstaller.swift"
    ).read_text(encoding="utf-8")
    assert "/api/client/releases/\\(channel).json" in resolution
    assert "github.com/maix00/FactorTester-Client/releases/latest/download" in resolution
    assert '[("server", server)]' in resolution
    assert '[("github", github)]' in resolution
    assert '"trusted-beta-release-public"' in resolution
    assert 'source == "server"' in resolution
    assert "minimumClient" in resolution
    assert "incompatibleClient" in resolution
    assert ".reloadIgnoringLocalCacheData" in resolution
    assert "api.github.com" not in resolution + controller
    assert "SHA256()" in store
    assert "prefix(2)" in store
    assert "NSWorkspace.shared.open" in installer
    assert "replaceItemAt" not in controller
    assert controller.index("AppUpdateStore.sha256") < controller.index(
        "AppInstallerInspector.inspect"
    )
    for label in ("当前版本", "可用版本", "运行状态"):
        assert label in status
    for label in ("更新详情", "客户端更新", "下载更新", "重启并更新"):
        assert label in view
    for label in (
        'Text("Main")', 'Text("Beta")', "最后检查", "自动下载更新",
    ):
        assert label in view
    assert "ClientReleaseStatusCard" not in view
    assert view.count(".buttonStyle(.borderedProminent)") == 1
    assert "checkAtLaunch" in app and "Task {" in app
    assert "runtimeActivationError" in app
    assert "try? await BundledRuntimeActivator.run()" not in app
    assert "6 * 60 * 60" in controller
    for contract in (
        "manifestDigestMismatch", "manifestSignatureMismatch",
        "bundleID == \"com.gtht.client\"", "VersionOrder.isNewer",
    ):
        assert contract in manifest + controller
    assert "hdiutil" in inspector
    assert "Developer ID Application" in inspector
    assert "source=Notarized Developer ID" in inspector
    assert "AppUpdateInstalling" in installer
    assert "Sparkle" in installer
    assert "ClientSidebar" in home
    assert "openTab: open" in home
    assert "approval" not in view.lower()


def test_macos_info_plist_uses_project_version_settings() -> None:
    project = (ROOT / "apple" / "project.yml").read_text(
        encoding="utf-8"
    )

    assert "CFBundleShortVersionString: $(MARKETING_VERSION)" in project
    assert "CFBundleVersion: $(CURRENT_PROJECT_VERSION)" in project


def test_macos_pins_sparkle_and_embeds_one_update_trust_anchor() -> None:
    project = (ROOT / "apple" / "project.yml").read_text(
        encoding="utf-8"
    )
    coordinator = (
        SOURCES / "Features" / "Updates" / "SparkleUpdateCoordinator.swift"
    ).read_text(encoding="utf-8")

    assert "https://github.com/sparkle-project/Sparkle" in project
    assert 'exactVersion: "2.9.2"' in project
    assert "package: Sparkle" in project
    assert "SUPublicEDKey" in project
    assert "SPUStandardUpdaterController" in coordinator
    assert "feedURLString(for updater: SPUUpdater)" in coordinator
    assert "setFeedURL" not in coordinator


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
    app = (SOURCES / "App" / "FactorTesterClientApp.swift").read_text()
    activator = (
        SOURCES / "Features" / "Updates" / "BundledRuntimeActivator.swift"
    ).read_text()
    assert "await BundledRuntimeActivator.run()" in app
    assert '"activate-bundle"' in activator
    assert '"--bundle-resources"' in activator


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
    local_profile_files = [
        profile_root / "LocalProfileController.swift",
        profile_root / "LocalProfileCommands.swift",
        profile_root / "LocalProfileSnapshotStore.swift",
    ]
    controller = "\n".join(
        path.read_text(encoding="utf-8") for path in local_profile_files
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
    for path in local_profile_files:
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 130
    for path in sorted(profile_root.glob("*.swift")):
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
    controller = "\n".join(
        (profile_root / filename).read_text(encoding="utf-8")
        for filename in (
            "LocalProfileController.swift", "LocalProfileCommands.swift",
        )
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


def test_macos_profiles_use_principal_scoped_default_workspace() -> None:
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
    assert "Documents/FactorTester/users/" in form
    assert "workspaceRoot" not in form
    assert "可见工作区" in view
    assert "Owner:" in view


def test_macos_settings_show_only_active_unified_workspace() -> None:
    settings_root = SOURCES / "Features" / "Settings"
    hub = (settings_root / "ClientSettingsHub.swift").read_text(
        encoding="utf-8"
    )
    view = (settings_root / "PersonalWorkspaceView.swift").read_text(
        encoding="utf-8"
    )
    controller = (
        settings_root / "PersonalWorkspaceController.swift"
    ).read_text(encoding="utf-8")

    assert "PersonalWorkspaceView()" in hub
    assert "LocalProfilesView()" not in hub
    assert "Profile、实时研究步骤、Trial Plan、义务与报告不属于设置" in hub
    assert "Documents/FactorTester/users" in view
    assert "personal-workspace/factor-library" in view
    assert "Profile 只链接 canonical repo 的独立 worktree" in view
    assert "当前 canonical 因子库" in view
    assert "Legacy quarantine" not in view
    assert "迁移" not in view
    assert '"user-layout", "show"' in controller
    assert '"user-layout", "migration"' not in controller
    assert "Process()" not in controller
    assert '"git"' not in controller


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

    assert "isPinnedLauncher" in navigation
    assert "case profile(id: String)" in navigation
    assert "case web(path: String)" in navigation
    assert "/api/account/password" in api
    assert ".products" in account
    assert ".factorLibrary" in account
    assert '"127.0.0.1"' in config
    assert '"8000"' in config


def test_macos_sidebar_exposes_profiles_account_and_bounded_research() -> None:
    navigation_root = SOURCES / "Navigation"
    sidebar = (navigation_root / "ClientSidebar.swift").read_text(
        encoding="utf-8"
    )
    tab_model = (navigation_root / "ClientTab.swift").read_text(
        encoding="utf-8"
    )
    home = (SOURCES / "Features" / "Home" / "HomeView.swift").read_text(
        encoding="utf-8"
    )
    dashboard = (
        SOURCES / "Features" / "Home" / "HomeDashboardView.swift"
    ).read_text(encoding="utf-8")
    profile_root = SOURCES / "Features" / "Profiles"
    directory = (profile_root / "ProfilesDirectoryView.swift").read_text(
        encoding="utf-8"
    )
    workspace = (profile_root / "ProfileWorkspaceView.swift").read_text(
        encoding="utf-8"
    )
    sections = (profile_root / "ProfileWorkspaceSections.swift").read_text(
        encoding="utf-8"
    )
    live = (profile_root / "ProfileLiveProcessView.swift").read_text(
        encoding="utf-8"
    )
    login = (SOURCES / "Features" / "Auth" / "LoginView.swift").read_text(
        encoding="utf-8"
    )
    server = (
        SOURCES / "Features" / "Settings" / "ServerSettingsView.swift"
    ).read_text(encoding="utf-8")
    projection_service = (
        SOURCES / "Networking" / "ProfileResearchService.swift"
    ).read_text(
        encoding="utf-8"
    )

    for label in (
        "主页", "研究", "因子库", "产品", "Profiles", "个人中心", "设置",
    ):
        assert label in sidebar + tab_model
    assert 'Section("已打开")' in sidebar
    assert "openTabs.filter(\\.isClosable)" in sidebar
    assert "TabView(selection:" not in home
    assert "LocalProfileController()" in home
    assert "ForEach(controller.profiles)" in directory
    assert "MaxA" not in directory and "MaxB" not in directory
    assert "所有进行中和已完成的研究统一从 Research" in workspace
    for label in ("实时过程", "Trial Plans", "Evidence"):
        assert label not in workspace
    assert "不轮询完整 trace" in sections + live
    for label in ("研究进度", "Profiles", "个人中心"):
        assert label in dashboard
    assert "Form {" not in login
    assert "Form {" not in server
    assert "DisclosureGroup" in server
    assert "127.0.0.1" in server and "8000" in server
    assert '"/api/profile-research"' in projection_service
    assert 'URLQueryItem(name: "limit", value: "50")' in projection_service
    assert '"If-None-Match"' in projection_service
    assert "/custom-factors/library" in tab_model
    assert "/custom-factors/editor" not in tab_model
    assert ".safeAreaInset(edge: .bottom" in sidebar
    assert ".onTapGesture { open(tab) }" in sidebar
    settings_hub = (
        SOURCES / "Features" / "Settings" / "ClientSettingsHub.swift"
    ).read_text(encoding="utf-8")
    account = (
        SOURCES / "Features" / "Account" / "AccountCenterView.swift"
    ).read_text(encoding="utf-8")
    assert (
        "case server, personalWorkspace, workspaces, language, updates"
        in settings_hub
    )
    assert "LocalProfilesView()" not in settings_hub
    assert "Button(\"打开 Profiles\"" in settings_hub
    assert "case account, security, productGroups, factorGrants" in account
    assert "case language" not in account


def test_macos_profile_directory_fails_closed_on_profile_deletion() -> None:
    profile_root = SOURCES / "Features" / "Profiles"
    lifecycle = (
        profile_root / "LocalProfileLifecycleController.swift"
    ).read_text(encoding="utf-8")
    card = (profile_root / "ProfileDirectoryCard.swift").read_text(
        encoding="utf-8"
    )
    receipt = (
        profile_root / "ProfileLifecycleReceiptView.swift"
    ).read_text(encoding="utf-8")

    for command in ("create", "deactivate", "purge"):
        assert f'"{command}"' in lifecycle
    assert '"delete"' not in lifecycle
    assert '"factor-worktree", "rollback"' in lifecycle
    assert "Process()" not in lifecycle
    assert "git " not in lifecycle.lower()
    assert "解绑并删除" not in card
    assert "可安全解绑 Worktree" in card
    assert "不删除 Git 分支、提交或 receipt" in receipt
    assert "清理已删除 Profile 的空目录" in receipt


def test_live_profile_ui_is_bounded_refreshable_and_source_free() -> None:
    service = (
        SOURCES / "Networking" / "ProfileResearchService.swift"
    ).read_text(encoding="utf-8")
    controller = (
        SOURCES / "Stores" / "ProfileLiveProcessController.swift"
    ).read_text(encoding="utf-8")
    live_root = SOURCES / "Features" / "Profiles"
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(live_root.glob("ProfileLive*.swift"))
    )
    ui_test = (
        ROOT / "apple" / "UITests" / "SidebarNavigationUITests.swift"
    ).read_text(encoding="utf-8")

    assert 'URLQueryItem(name: "limit", value: "50")' in service
    assert '"If-None-Match"' in service
    assert "statusCode == 304" in service
    assert 'line.hasPrefix("data:")' in service
    assert "max(" in controller and "minimumIntervalSeconds" in controller
    assert "directive.terminal" in controller
    assert "Task.checkCancellation()" in controller
    assert "nextTimelineCursor" in controller
    assert "loadEarlierTimeline" in combined
    assert "ResearchReportIndex.load" in combined
    assert "initialWorkspaceID: item.workspaceID" in combined
    assert "selectedBranchID" in combined
    for forbidden in ("stdout", "full trace", "markdown"):
        assert forbidden not in service.lower() + controller.lower()
    for identifier in (
        "sidebar.launch.home",
        "sidebar.launch.research",
        "sidebar.launch.profiles",
        "sidebar.launch.account",
        "sidebar.launch.settings",
        "sidebar.launch.web:factor-library",
        "sidebar.launch.web:products",
    ):
        assert identifier in ui_test
