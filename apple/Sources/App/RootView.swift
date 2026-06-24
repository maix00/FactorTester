import SwiftUI

/// 根视图：未配置服务器 → 强制配置；已配置 → 进入首页。
struct RootView: View {
    @EnvironmentObject var config: ServerConfig

    var body: some View {
        if config.isConfigured {
            HomeView()
        } else {
            ServerSettingsView(isInitialSetup: true)
        }
    }
}
