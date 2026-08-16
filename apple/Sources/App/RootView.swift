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
                    Text(L10n.text("正在寻找 FactorTester 服务器…"))
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            case .ready:
                ClientWebShellView()
            case .manual:
                ServerSettingsView(isInitialSetup: true) {
                    Task { @MainActor in
                        if let endpoint = managerConfig.baseURL {
                            await authenticateEnrolledPublicDeviceIfNeeded(
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
            await authenticateEnrolledPublicDeviceIfNeeded(at: endpoint)
            state = .ready
        } catch {
            state = .manual
        }
    }

    @MainActor
    private func authenticateEnrolledPublicDeviceIfNeeded(at endpoint: URL) async {
        guard let host = endpoint.host,
              !ManagerEndpointPolicy.isPrivateNetwork(host),
              ManagerDeviceKeyStore.load() != nil else {
            return
        }
        // A missing or revoked device is non-fatal: the Web shell must still
        // show its public visitor compliance page. A successful challenge
        // stores the Manager session before WebView creation.
        _ = try? await ManagerDeviceAuthenticationService.shared.authenticate(
            endpoint: endpoint
        )
    }
}
