import SwiftUI

@main
struct FactorTesterClientApp: App {
    @StateObject private var config = ServerConfig.shared
    @StateObject private var session = SessionStore()
    @StateObject private var registry = ModuleRegistry()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(config)
                .environmentObject(session)
                .environmentObject(registry)
        }
        #if os(macOS)
        .defaultSize(width: 1000, height: 720)
        #endif
    }
}
