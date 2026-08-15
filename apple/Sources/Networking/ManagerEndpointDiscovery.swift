import Foundation

/// Selects the first public Manager returned by a server-side network
/// projection. The client never derives or embeds a public IP address.
@MainActor
final class ManagerEndpointDiscoveryService {
    static let shared = ManagerEndpointDiscoveryService()

    private init() {}

    func selectNearestPublicManagerIfNeeded() async -> ManagerPublicTarget? {
        let manager = ManagerConfig.shared
        guard manager.shouldDiscoverNearestPublicManager,
              let bootstrap = manager.baseURL else {
            return nil
        }

        let info: ManagerNetworkInfo
        do {
            info = try await ManagerNetworkInfoService.shared.fetch(
                endpoint: bootstrap
            )
        } catch {
            // A missing local Docker stack is not a client-build or login
            // failure. Keep the bootstrap endpoint so Settings can diagnose
            // it and the user can enter a Manager manually.
            return nil
        }
        guard let target = info.nearestPublicTarget,
              target.endpoint != bootstrap,
              target.endpoint.host != nil else {
            return nil
        }

        manager.saveAutoDiscovered(
            endpoint: target.endpoint,
            serverID: target.serverID
        )

        // An already enrolled native key may authenticate on the selected
        // public origin. Never create a new public device implicitly here;
        // enrollment remains an explicit Settings/device-authorization flow.
        if ManagerDeviceKeyStore.load() != nil {
            _ = try? await ManagerDeviceAuthenticationService.shared.authenticate(
                endpoint: target.endpoint
            )
        }
        return target
    }
}
