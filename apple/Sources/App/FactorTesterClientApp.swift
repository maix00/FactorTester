import SwiftUI

enum AppRuntimePolicy {
    static func shouldLoadUserState(
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> Bool {
        environment["XCTestConfigurationFilePath"] == nil
            && environment["XCTestSessionIdentifier"] == nil
    }
}

@main
struct FactorTesterClientApp: App {
    @StateObject private var config = ServerConfig.shared
    @StateObject private var managerConfig = ManagerConfig.shared
    @StateObject private var session = SessionStore()
    @StateObject private var registry = ModuleRegistry()
    @StateObject private var updates = ClientReleaseController()
    @StateObject private var languageStore = LanguageStore()
    @State private var runtimeActivationError: String?

    var body: some Scene {
        #if os(macOS)
        #if DEBUG
        // UI tests use Debug and need a fresh window on every launch. A
        // macOS `Window` scene may restore with its single window closed,
        // leaving XCTest attached to a menu-only process. Release builds keep
        // the single-window scene used by the shipped client.
        WindowGroup("FTClient") {
            windowRoot
        }
        .defaultSize(width: 1000, height: 720)
        #else
        Window("FTClient", id: "main") {
            productionRoot
        }
        .defaultSize(width: 1000, height: 720)
        #endif
        #else
        WindowGroup {
            productionRoot
        }
        #endif
    }

    #if DEBUG
    @ViewBuilder
    private var windowRoot: some View {
        if ProcessInfo.processInfo.arguments.contains(
            "--ui-test-report-navigation"
        ) {
            ResearchReportNavigationFixtureView()
        } else {
            productionRoot
        }
    }
    #endif

    private var productionRoot: some View {
        Group {
            if AppRuntimePolicy.shouldLoadUserState() {
                RootView()
            } else {
                Color.clear
            }
        }
            .environmentObject(config)
            .environmentObject(managerConfig)
            .environmentObject(session)
            .environmentObject(registry)
            .environmentObject(updates)
            .environmentObject(languageStore)
            .environment(
                \.locale,
                languageStore.locale
            )
            .alert(
                L10n.text("客户端运行时未能激活"),
                isPresented: Binding(
                    get: { runtimeActivationError != nil },
                    set: { if !$0 { runtimeActivationError = nil } }
                )
            ) {
                Button(L10n.text("知道了")) {
                    runtimeActivationError = nil
                }
            } message: {
                Text(runtimeActivationError ?? "")
            }
            .onOpenURL { url in
                updates.handleUpdateCommand(url)
            }
            #if os(macOS)
            .task {
                Task { await updates.checkAtLaunch() }
                do {
                    try await BundledRuntimeActivator.run()
                } catch {
                    runtimeActivationError = error.localizedDescription
                }
                _ = try? LegacyAppNameMigration.run()
            }
            #endif
    }
}
