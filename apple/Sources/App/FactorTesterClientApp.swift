import SwiftUI

enum AppRuntimePolicy {
    static let windowRestorationPreference = "ApplePersistenceIgnoreState"

    static func shouldLoadUserState(
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> Bool {
        environment["XCTestConfigurationFilePath"] == nil
            && environment["XCTestSessionIdentifier"] == nil
    }

    static func shouldUseSystemWindowReopen(
        hasVisibleWindows: Bool
    ) -> Bool {
        !hasVisibleWindows
    }

    static func disableWindowRestoration(
        defaults: UserDefaults = .standard
    ) {
        defaults.set(true, forKey: windowRestorationPreference)
    }
}

@main
struct FactorTesterClientApp: App {
    #if os(macOS)
    @NSApplicationDelegateAdaptor(FTClientAppDelegate.self)
    private var appDelegate
    #endif
    @StateObject private var config = ServerConfig.shared
    @StateObject private var managerConfig = ManagerConfig.shared
    @StateObject private var session = SessionStore()
    @StateObject private var registry = ModuleRegistry()
    @StateObject private var updates = ClientReleaseController()
    @StateObject private var languageStore = LanguageStore()
    @State private var runtimeActivationError: String?

    init() {
        #if os(macOS)
        // FTClient is deliberately single-window. Persisting a closed scene
        // as application restoration state can make the next cold launch
        // menu-only. Disable AppKit state restoration before
        // SwiftUI constructs its scenes; the report/session state has its own
        // durable stores and must not depend on NSWindow restoration.
        AppRuntimePolicy.disableWindowRestoration()
        #endif
    }

    var body: some Scene {
        #if os(macOS)
        Window("FTClient", id: "main") {
            #if DEBUG
            windowRoot
            #else
            productionRoot
            #endif
        }
        .defaultSize(width: 1000, height: 720)
        #else
        WindowGroup {
            productionRoot
        }
        #endif
    }

    #if DEBUG
    @ViewBuilder
    private var windowRoot: some View {
        productionRoot
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
            .task(id: languageSynchronizationID) {
                await languageStore.synchronize(
                    principal: session.user?.username
                )
            }
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

    private var languageSynchronizationID: String {
        "\(session.user?.username ?? "")|\(session.isManagerLoggedIn)"
    }
}

#if os(macOS)
@MainActor
private final class FTClientAppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldHandleReopen(
        _ sender: NSApplication,
        hasVisibleWindows flag: Bool
    ) -> Bool {
        if AppRuntimePolicy.shouldUseSystemWindowReopen(
            hasVisibleWindows: flag
        ) {
            return true
        }
        return false
    }
}
#endif
