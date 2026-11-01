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
    @State private var deviceLoginPath: String?

    var body: some View {
        WebPageView(
            path: deviceLoginPath ?? "/app",
            presentation: .standalone,
            webSession: webSession,
            onExternalURL: openExternalURL
        )
        .id(managerConfig.baseURL?.absoluteString ?? "manager-unconfigured")
        .onAppear { acceptDeviceHandoff(managerConfig.pendingDeviceLogin) }
        .onChange(of: managerConfig.pendingDeviceLogin) { value in acceptDeviceHandoff(value) }
        .onChange(of: session.isLoggedIn) { loggedIn in
            if loggedIn { deviceLoginPath = nil }
        }
        .task(id: "\(session.isLoggedIn)|\(session.user?.organizationId ?? "")") {
            guard deviceLoginPath == nil else { return }
            let previousEndpoint = managerConfig.baseURL
            let previousIdentity = session.user?.localResearchIdentity
            let wasLoggedIn = session.isLoggedIn
            let selected = await ManagerEndpointDiscoveryService.shared
                .selectBestManager(
                    organizationID: session.user?.organizationId,
                    expectedUsername: session.user?.username
                )
            // Do not send stored credentials to a newly discovered Manager.
            // Check the stable ID and same-realm subject. Cross-realm
            // equivalence still requires a separate federation proof.
            if wasLoggedIn, session.isLoggedIn, session.user?.localResearchIdentity == previousIdentity,
               selected != nil, previousEndpoint != managerConfig.baseURL {
                _ = await session.validateManagerChange(expectedIdentity: previousIdentity)
            }
            await releaseController.refresh(force: false)
        }
    }

    private func acceptDeviceHandoff(_ url: URL?) {
        guard let url, let parts = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let query = parts.percentEncodedQuery else { return }
        deviceLoginPath = parts.percentEncodedPath + "?" + query
        managerConfig.clearDeviceLogin()
    }

    private func openExternalURL(_ url: URL) {
        _ = openURL(url)
    }
}
