import SwiftUI

@main
struct FactorTesterClientApp: App {
    @AppStorage("client.language") private var language = AppLanguage.system.rawValue
    @StateObject private var config = ServerConfig.shared
    @StateObject private var session = SessionStore()
    @StateObject private var registry = ModuleRegistry()
    @StateObject private var updates = ClientReleaseController()
    @State private var runtimeActivationError: String?

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(config)
                .environmentObject(session)
                .environmentObject(registry)
                .environment(
                    \.locale,
                    AppLanguage(rawValue: language)?.locale ?? .autoupdatingCurrent
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
        #if os(macOS)
        .defaultSize(width: 1000, height: 720)
        #endif
    }
}
