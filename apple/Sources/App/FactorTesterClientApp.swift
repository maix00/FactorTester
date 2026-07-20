import SwiftUI

@main
struct FactorTesterClientApp: App {
    @AppStorage("client.language") private var language = AppLanguage.system.rawValue
    @StateObject private var config = ServerConfig.shared
    @StateObject private var session = SessionStore()
    @StateObject private var registry = ModuleRegistry()

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
                #if os(macOS)
                .task { try? LegacyAppNameMigration.run() }
                #endif
        }
        #if os(macOS)
        .defaultSize(width: 1000, height: 720)
        #endif
    }
}
