import SwiftUI

/// 根视图：先解析 Manager 引导地址；只有引导不可达时才要求手动配置。
struct RootView: View {
    @EnvironmentObject private var managerConfig: ManagerConfig
    @State private var state: BootstrapState = .checking

    private enum BootstrapState {
        case checking
        case ready
        case manual
    }

    var body: some View {
        Group {
            switch state {
            case .checking:
                ProgressView {
                    Text(L10n.text("正在寻找 TradeResearch 服务器…"))
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            case .ready:
                ClientWebShellView()
            case .manual:
                ServerSettingsView(isInitialSetup: true) {
                    Task { @MainActor in
                        if let endpoint = managerConfig.baseURL {
                            await beginEnrolledDeviceLoginIfNeeded(
                                at: endpoint
                            )
                        }
                        state = .ready
                    }
                }
            }
        }
        .task { await resolveManager() }
    }

    @MainActor
    private func resolveManager() async {
        if managerConfig.shouldDiscoverNearestPublicManager {
            let selected = await ManagerEndpointDiscoveryService.shared
                .selectBestManager()
            state = selected == nil ? .manual : .ready
            return
        }

        guard managerConfig.isValid, let endpoint = managerConfig.baseURL else {
            state = .manual
            return
        }
        do {
            _ = try await ManagerNetworkInfoService.shared.fetch(endpoint: endpoint)
            await beginEnrolledDeviceLoginIfNeeded(at: endpoint)
            state = .ready
        } catch {
            state = .manual
        }
    }

    @MainActor
    private func beginEnrolledDeviceLoginIfNeeded(at endpoint: URL) async {
        guard ManagerDeviceKeyStore.load() != nil else { return }
        if !ManagerSessionTokenStore.read(for: endpoint).isEmpty,
           let user = try? await APIClient.shared.me(), user.localResearchIdentity != nil { return }
        if let handoff = try? await ManagerDeviceAuthenticationService.shared.beginOIDCLogin(endpoint: endpoint) {
            managerConfig.queueDeviceLogin(handoff, for: endpoint)
        }
    }
}
