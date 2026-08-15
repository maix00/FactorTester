import SwiftUI

/// The main FTClient surface: one Web shell plus a small native capability
/// layer.  The Web app owns the home page, feature entry, sidebar, and opened
/// tabs; Swift remains responsible for Keychain-backed authentication,
/// client settings, local capabilities, and Sparkle updates.
struct ClientWebShellView: View {
    @EnvironmentObject private var releaseController: ClientReleaseController
    @EnvironmentObject private var session: SessionStore
    @EnvironmentObject private var languageStore: LanguageStore
    @Environment(\.openURL) private var openURL

    @State private var webSession = WebPageSession()
    @State private var showClientSettings = false
    @State private var showRestartPrompt = false
    @State private var nativeTab: ClientTab?
    @StateObject private var profiles = LocalProfileController()
    @StateObject private var tabSessions = ClientTabSessionStore()

    var body: some View {
        WebPageView(
            path: "/",
            presentation: .standalone,
            webSession: webSession,
            onExternalURL: openExternalURL
        )
        .toolbar {
            ClientWebShellToolbar(
                controller: releaseController,
                openSettings: openClientSettings,
                confirmRestart: { showRestartPrompt = true }
            )
        }
        .alert(
            L10n.text("更新已准备好"),
            isPresented: $showRestartPrompt
        ) {
            Button(L10n.text("稍后"), role: .cancel) {}
            Button(L10n.text("重启并更新"), action: restartToApply)
        } message: {
            Text(L10n.text("更新已下载并验证，重启 FTClient 后完成安装。"))
        }
        .sheet(isPresented: $showClientSettings) {
            ClientSettingsHub(open: openNativeTab)
                .environmentObject(session)
                .environmentObject(releaseController)
                .environmentObject(languageStore)
        }
        .sheet(item: $nativeTab) { tab in
            ClientTabView(
                tab: tab,
                profiles: profiles,
                tabSession: tabSessions.session(for: tab.id),
                open: openNativeTab,
                isActive: true
            )
            .environmentObject(session)
            .environmentObject(languageStore)
        }
        .task {
            await releaseController.refresh(force: false)
        }
    }

    private func openClientSettings() {
        showClientSettings = true
    }

    private func openNativeTab(_ tab: ClientTab) {
        showClientSettings = false
        nativeTab = tab
    }

    private func openExternalURL(_ url: URL) {
        _ = openURL(url)
    }

    private func restartToApply() {
        Task { await releaseController.restartToApply() }
    }
}

private struct ClientWebShellToolbar: ToolbarContent {
    @ObservedObject var controller: ClientReleaseController
    let openSettings: () -> Void
    let confirmRestart: () -> Void

    var body: some ToolbarContent {
        ToolbarItemGroup(placement: .automatic) {
            if controller.isUpdateReady {
                Button(action: confirmRestart) {
                    toolbarLabel("重启并更新", systemImage: "arrow.clockwise")
                }
                .help(L10n.text("更新已准备好；重启后安装"))
                .accessibilityIdentifier("client-shell.update-restart")
            } else if controller.hasAvailableUpdate {
                Button {
                    Task { await controller.update() }
                } label: {
                    toolbarLabel("下载更新", systemImage: "arrow.down.circle")
                }
                .disabled(controller.isWorking)
                .help(L10n.format("有更新：下载并准备 %@", controller.latestVersion))
                .accessibilityIdentifier("client-shell.update-download")
            }

            Menu {
                Button {
                    Task { await controller.refresh() }
                } label: {
                    toolbarLabel("检查更新", systemImage: "arrow.triangle.2.circlepath")
                }
                Button(action: openSettings) {
                    toolbarLabel("客户端设置", systemImage: "gearshape")
                }
            } label: {
                toolbarLabel(
                    "客户端更新",
                    systemImage: controller.isWorking
                        ? "arrow.triangle.2.circlepath.circle"
                        : "arrow.down.app"
                )
            }
            .disabled(controller.isWorking && !controller.hasAvailableUpdate)
            .accessibilityIdentifier("client-shell.update-menu")
        }
    }

    private func toolbarLabel(_ title: String, systemImage: String) -> some View {
        Label {
            Text(verbatim: L10n.text(title))
        } icon: {
            Image(systemName: systemImage)
        }
    }
}
