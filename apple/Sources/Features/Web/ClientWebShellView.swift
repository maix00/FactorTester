import SwiftUI

/// The main FTClient surface. The Web app owns the home page, feature entry,
/// sidebar, opened tabs, and the unified settings entry; Swift remains
/// responsible for Keychain-backed authentication and local client services.
struct ClientWebShellView: View {
    @EnvironmentObject private var releaseController: ClientReleaseController
    @EnvironmentObject private var session: SessionStore
    @EnvironmentObject private var managerConfig: ManagerConfig
    @Environment(\.openURL) private var openURL

    @State private var webSession = WebPageSession()

    var body: some View {
        WebPageView(
            path: "/",
            presentation: .standalone,
            webSession: webSession,
            onExternalURL: openExternalURL
        )
        .id(managerConfig.baseURL?.absoluteString ?? "manager-unconfigured")
        .task(id: "\(session.isLoggedIn)|\(session.user?.organizationId ?? "")") {
            let wasLoggedIn = session.isLoggedIn
            let selected = await ManagerEndpointDiscoveryService.shared
                .selectBestManager(
                    organizationID: session.user?.organizationId
                )
            // Manager cookies/tokens are origin-scoped. When an authenticated
            // user moves from the public Manager to an organization-owned
            // internal Manager, refresh the same credentials on that new
            // endpoint before the Web shell is reloaded.
            if wasLoggedIn, selected != nil {
                _ = await session.refresh()
            }
            await releaseController.refresh(force: false)
        }
    }

    private func openExternalURL(_ url: URL) {
        _ = openURL(url)
    }
}
