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
            path: "/app",
            presentation: .standalone,
            webSession: webSession,
            onExternalURL: openExternalURL
        )
        .id(managerConfig.baseURL?.absoluteString ?? "manager-unconfigured")
        .task(id: "\(session.isLoggedIn)|\(session.user?.organizationId ?? "")") {
            let previousEndpoint = managerConfig.baseURL
            let previousIdentity = session.user?.stableIdentityID
            let wasLoggedIn = session.isLoggedIn
            let selected = await ManagerEndpointDiscoveryService.shared
                .selectBestManager(
                    organizationID: session.user?.organizationId,
                    expectedUsername: session.user?.username
                )
            // Do not send stored credentials to a newly discovered Manager.
            // Only a target session for the same stable identity is accepted.
            if wasLoggedIn, session.isLoggedIn, session.user?.stableIdentityID == previousIdentity,
               selected != nil, previousEndpoint != managerConfig.baseURL {
                _ = await session.validateManagerChange(expectedIdentityID: previousIdentity)
            }
            await releaseController.refresh(force: false)
        }
    }

    private func openExternalURL(_ url: URL) {
        _ = openURL(url)
    }
}
