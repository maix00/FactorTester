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
    root = (SOURCES / "App" / "RootView.swift").read_text(encoding="utf-8")
    web_shell = (
        SOURCES / "Features" / "Web" / "ClientWebShellView.swift"
    ).read_text(encoding="utf-8")
    app = (SOURCES / "App" / "FactorTesterClientApp.swift").read_text(
        encoding="utf-8"
    )
    assert "/api/client/releases/beta.xml" in controller
    assert "ManagerConfig.shared.url" in controller
    assert "ServerConfig.shared.url" not in controller
    assert "releases/latest/download/appcast.xml" in controller
    assert "SparkleUpdateCoordinator" in controller
    for label in ("客户端更新", "下载更新", "重启并更新", "检查更新"):
        assert label in view
    for label in (
        'Text("Main")', 'Text("Beta")', "lastChecked", "自动下载更新",
    ):
        assert label in view
    assert "ClientReleaseStatusCard" not in view
    assert view.count(".buttonStyle(.borderedProminent)") == 1
    assert "checkAtLaunch" in app and "Task {" in app
    assert "runtimeActivationError" in app
    assert "try? await BundledRuntimeActivator.run()" not in app
    assert "6 * 60 * 60" in controller
    assert ".onOpenURL" in app
    assert "handleUpdateCommand" in controller
    assert 'pendingExternalAction = action' in controller
    assert 'case "download"' in controller
    assert "ClientWebShellView()" in root
    assert "ClientWebShellToolbar" not in web_shell
    assert ".toolbar" in web_shell
    assert "showingServerSettings" in web_shell
    assert "ServerSettingsView" in web_shell
    web_page = (SOURCES / "Features" / "Web" / "WebPageView.swift").read_text(
        encoding="utf-8"
    )
    assert 'X-FactorTester-Client-Access' in web_page
    assert '"ftclient"' in web_page
    assert "approval" not in view.lower()
    assert 'Window("FTClient", id: "main")' in app
    assert "WindowGroup" in app


def test_macos_info_plist_uses_project_version_settings() -> None:
    project = (ROOT / "apple" / "project.yml").read_text(
        encoding="utf-8"
    )

    assert "CFBundleShortVersionString: $(MARKETING_VERSION)" in project
    assert "CFBundleVersion: $(CURRENT_PROJECT_VERSION)" in project
    assert "SPARKLE_PUBLIC_ED_KEY:" in project


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
    assert "CFBundleURLSchemes:" in project
    assert "- factortester" in project
    assert "SPUUpdater(" in coordinator
    assert "SPUUserDriver" in coordinator
    assert "downloadAvailableUpdate" in coordinator
    assert "installAndRelaunch" in coordinator
    assert "feedURLString(for updater: SPUUpdater)" in coordinator
    assert "allowedChannels(for updater: SPUUpdater)" in coordinator
    assert "setFeedURL" not in coordinator


def test_macos_persists_update_status_for_cli_observation() -> None:
    controller = (
        SOURCES / "Features" / "Settings" / "ClientReleaseController.swift"
    ).read_text(encoding="utf-8")
    store = (
        SOURCES / "Features" / "Updates" / "AppUpdateStatusStore.swift"
    ).read_text(encoding="utf-8")
    assert "AppUpdateStatusStore.write" in controller
    assert '"app-update-status.json"' in store
    assert '"state"' in store


def test_release_signing_is_inside_out_without_codesign_deep() -> None:
    source = (ROOT / "scripts" / "release" / "build.py").read_text(
        encoding="utf-8"
    )

    assert '"--deep"' not in source
    assert "signables.sort" in source
    assert '"--all-architectures"' in source


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


def test_macos_reuses_one_web_view_per_tab_session() -> None:
    web = (SOURCES / "Features" / "Web" / "WebPageView.swift").read_text(
        encoding="utf-8"
    )
    session = (SOURCES / "Navigation" / "ClientTabSession.swift").read_text(
        encoding="utf-8"
    )
    tab = (SOURCES / "Navigation" / "ClientTabView.swift").read_text(
        encoding="utf-8"
    )

    assert "final class WebPageSession" in web
    assert "@State private var ownedWebSession = WebPageSession()" in web
    assert "private var activeWebSession: WebPageSession" in web
    assert "webSession ?? ownedWebSession" in web
    assert "webSession?.webView" in web
    assert "webSession?.loadedURL" in web
    assert "existing.removeFromSuperview()" in web
    assert "webView.navigationDelegate = nil" in web
    assert "var webPageSession: WebPageSession?" in session
    assert "ensureWebPageSession()" in session
    assert "tabSession.ensureWebPageSession()" in tab


def test_macos_research_sections_share_embedded_web_report_route_and_native_links() -> None:
    view = (
        SOURCES / "Features" / "Profiles" / "ResearchModuleView.swift"
    ).read_text(encoding="utf-8")
    assert view.count("WebPageView(") == 1
    assert '"/research?section=\\(tabSession.researchSection.rawValue)"' in view
    assert "Picker(" not in view
    assert "webSession: tabSession.ensureWebPageSession()" in view
    assert "onReference: openReferencePage" in view
    assert "onNavigation: openResearchPath" in view
    assert "onExternalURL: openExternalURL" in view


def test_job_detail_uses_canonical_timestamps_without_duplicate_compatibility_rows() -> None:
    source = (
        SOURCES / "Features" / "Jobs" / "TestJobsService.swift"
    ).read_text(encoding="utf-8")
    assert '"created_at", "created_at（提交时间）", timestampValue(value["created_at"] ?? value["submitted_at"])' in source
    assert '"finished_at", "finished_at（完成时间）", timestampValue(value["finished_at"] ?? value["completed_at"])' in source
    assert '("submitted_at", "submitted_at（提交时间，兼容字段）"' not in source
    assert '("completed_at", "completed_at（完成时间，兼容字段）"' not in source
    assert '"job_spec_hash", "job_spec_hash（JobSpec 哈希）"' in source
    assert '"run_spec_hash", "run_spec_hash（RunSpec 哈希）"' in source


def test_macos_manages_provider_neutral_local_profiles() -> None:
    profile_root = SOURCES / "Features" / "Profiles"
    local_profile_files = [
        profile_root / "LocalProfileController.swift",
        profile_root / "LocalProfileControllerRuntime.swift",
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
        path.read_text(encoding="utf-8") for path in local_profile_files
    )

    assert '["client", "profile", "list"]' in controller
    assert '"profile", "agent", "set"' in controller
    assert "LocalProfilesView()" in settings
    assert "审批" not in combined
    for forbidden in ("Codex", "model_id", "runtime_id", "password"):
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
    controller = "\n".join(
        (profile_root / filename).read_text(encoding="utf-8")
        for filename in (
            "LocalProfileController.swift", "LocalProfileCommands.swift",
        )
    )
    keychain = (SOURCES / "Services" / "KeychainStore.swift").read_text(
        encoding="utf-8"
    )

    assert not (profile_root / "LocalAdapterProfileForm.swift").exists()
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
    view = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            profile_root / "LocalProfilesView.swift",
            profile_root / "WorkspaceRegistryRow.swift",
            SOURCES / "Features" / "Settings" / "PersonalWorkspaceView.swift",
        )
    )
    assert 'json["workspaces"]' in model
    assert 'json["owner_ref"]' in model
    assert "Documents/FactorTester/users" in view
    assert "LocalProfileForm" not in view
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

    assert "PersonalWorkspaceView(openProfiles:" in hub
    assert "LocalProfilesView()" not in hub
    workspace_view = view + (SOURCES / "Features" / "Profiles" / "ProfileWorkspaceView.swift").read_text(encoding="utf-8")
    assert "Profile、实时研究步骤、Trial Plan、义务与报告" in workspace_view
    assert "Documents/FactorTester/users" in view
    assert "personal-workspace/factor-library" in view
    assert "各个研究现场的独立 worktree" in view
    assert "本地 canonical 因子库" in view
    assert "Legacy quarantine" not in view
    assert "迁移" not in view
    assert '"factor-library", "workspace", "user", "download"' in controller
    assert '"factor-library", "workspace", "user", "upload"' in controller
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
    assert "AccountSettingsView()" in account
    assert ".products" not in account
    assert ".factorLibrary" not in account
    assert '"127.0.0.1"' in config
    assert "baseURL" in config and "port" in config


def test_macos_web_shell_exposes_profiles_account_and_bounded_research() -> None:
    navigation_root = SOURCES / "Navigation"
    tab_model = (navigation_root / "ClientTab.swift").read_text(
        encoding="utf-8"
    )
    tab_view = (navigation_root / "ClientTabView.swift").read_text(
        encoding="utf-8"
    )
    root = (SOURCES / "App" / "RootView.swift").read_text(encoding="utf-8")
    web_shell = (
        SOURCES / "Features" / "Web" / "ClientWebShellView.swift"
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

    for label in ("研究", "因子库", "产品", "设置"):
        assert label in tab_model
    assert "个人中心" not in tab_model
    assert "ClientWebShellView()" in root
    assert "WebPageView(" in web_shell
    assert "LocalProfileController()" not in web_shell
    assert "ClientSettingsHub" not in web_shell
    assert "case .profiles:" in tab_view
    assert "case .accountSettings:" in tab_view
    assert "List(controller.profiles)" in directory
    assert "MaxA" not in directory and "MaxB" not in directory
    assert "所有进行中和已完成的研究统一从 Research" in workspace
    for label in ("实时过程", "Trial Plans", "Evidence"):
        assert label not in workspace
    assert "不轮询完整 trace" in sections + live
    assert "Form {" not in login
    assert "Form {" not in server
    assert "SettingsEditableText" in server
    assert "managerPort = \"7998\"" in server
    assert '"/api/profile-research"' in projection_service
    assert 'URLQueryItem(name: "limit", value: "50")' in projection_service
    assert '"If-None-Match"' in projection_service
    assert 'path: "/factors"' in tab_model
    assert 'route = ("/factors/family/", "function", reference.targetRef)' in tab_model
    assert "/custom-factors/editor" not in tab_model
    settings_hub = (
        SOURCES / "Features" / "Settings" / "ClientSettingsHub.swift"
    ).read_text(encoding="utf-8")
    account = (
        SOURCES / "Features" / "Account" / "AccountCenterView.swift"
    ).read_text(encoding="utf-8")
    assert (
        "case account, server, workspace, adapters, localResearch, language, updates"
        in settings_hub
    )
    assert "LocalProfilesView()" not in settings_hub
    assert "open(.profiles)" in settings_hub
    assert "case session, register, password" in account
    assert "case language" not in account


def test_macos_profile_directory_fails_closed_on_profile_deletion() -> None:
    profile_root = SOURCES / "Features" / "Profiles"
    lifecycle = (
        profile_root / "LocalProfileLifecycleController.swift"
    ).read_text(encoding="utf-8")
    directory = (profile_root / "ProfilesDirectoryView.swift").read_text(
        encoding="utf-8"
    )
    receipt = (
        profile_root / "ProfileLifecycleReceiptView.swift"
    ).read_text(encoding="utf-8")

    for command in ("create", "deactivate", "purge"):
        assert f'"{command}"' in lifecycle
    assert '"delete"' not in lifecycle
    assert '"factor-worktree"' not in lifecycle
    assert '"rollback"' not in lifecycle
    assert "Process()" not in lifecycle
    assert "git " not in lifecycle.lower()
    assert not (profile_root / "ProfileDirectoryCard.swift").exists()
    assert "打开 Profile" in directory
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
    assert "loadEarlierTimeline" in controller
    assert "WebPageView(" in combined
    assert "localReportPath" in combined
    assert "path: reportPath" in combined
    assert "initialWorkspaceID: item.workspaceID" in combined
    assert "selectedBranchID" in combined
    for forbidden in ("stdout", "full trace", "markdown"):
        assert forbidden not in service.lower() + controller.lower()
    assert "WebShellNavigationUITests" in ui_test
    assert 'app.buttons["sidebar.launch.home"]' in ui_test
    assert "XCTAssertFalse" in ui_test
