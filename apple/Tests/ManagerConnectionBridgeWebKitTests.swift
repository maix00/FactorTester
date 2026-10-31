import Foundation
import WebKit
import XCTest
@testable import FTClient

@MainActor
final class ManagerConnectionBridgeWebKitTests: XCTestCase, WKNavigationDelegate {
    private var loaded: XCTestExpectation?
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { loaded?.fulfill() }

    func testDeniedTargetClearsNativeIdentityAndSelectsTarget() async throws {
        let value: [String: Any] = ["username": "alice", "keep_login": true,
                                    "keycloak_issuer": "https://identity.test/realm", "keycloak_subject": "subject", "tr_identity_id": "alice-id"]
        let user = try JSONDecoder().decode(UserInfo.self, from: JSONSerialization.data(withJSONObject: value))
        let session = SessionStore(api: ManagerBridgeTestAPI(user: user), managerAPI: ManagerBridgeTestManager(), bridge: { _ in true }, credentialLoader: { nil })
        let endpoint = try XCTUnwrap(ManagerConfig.shared.baseURL)
        var applied: URL?
        var targetUnavailable = true
        let content = WKUserContentController()
        content.addScriptMessageHandler(ManagerConnectionBridge(session: session, endpoint: endpoint, probe: { _, identity, username in
            XCTAssertEqual(identity?.stableID, "alice-id")
            XCTAssertEqual(username, "alice")
            return targetUnavailable ? .unavailable : .unauthorized
        }, apply: { applied = $0 }), contentWorld: .page, name: ManagerConnectionBridgeContract.messageName)
        let config = WKWebViewConfiguration(); config.websiteDataStore = .nonPersistent(); config.userContentController = content
        let view = WKWebView(frame: .zero, configuration: config); view.navigationDelegate = self
        loaded = expectation(description: "Manager test page")
        view.loadHTMLString("<html><body>Manager</body></html>", baseURL: endpoint)
        await fulfillment(of: [try XCTUnwrap(loaded)], timeout: 10)
        let capabilities = try await message(view, ["action": "capabilities"])
        XCTAssertEqual(capabilities["success"] as? Bool, true)
        XCTAssertEqual(session.user?.stableIdentityID, "alice-id")
        let target = "https://test-manager.invalid:54321"
        let unavailable = try await message(view, ["action": "switch", "url": target])
        XCTAssertEqual(unavailable["code"] as? String, "manager_unavailable")
        XCTAssertEqual(session.user?.stableIdentityID, "alice-id")
        XCTAssertNil(applied)
        targetUnavailable = false
        let result = try await message(view, ["action": "switch", "url": target])
        XCTAssertEqual(result["url"] as? String, target)
        XCTAssertEqual(result["auth_state"] as? String, "unauthorized")
        XCTAssertNil(session.user)
        XCTAssertEqual(applied?.host, "test-manager.invalid")
        content.removeScriptMessageHandler(forName: ManagerConnectionBridgeContract.messageName)
    }

    private func message(_ view: WKWebView, _ input: [String: Any]) async throws -> [String: Any] {
        let result = try await view.callAsyncJavaScript("return await window.webkit.messageHandlers.tradeResearchManager.postMessage(input)",
                                                       arguments: ["input": input], in: nil, contentWorld: .page)
        return try XCTUnwrap(result as? [String: Any])
    }
}

private final class ManagerBridgeTestAPI: SessionAPI {
    let user: UserInfo
    init(user: UserInfo) { self.user = user }
    func me() async throws -> UserInfo { user }
    func login(username: String, password: String) async throws -> AuthResponse { throw APIError.unauthorized("no") }
    func register(username: String, password: String, organizationId: String) async throws -> AuthResponse { throw APIError.unauthorized("no") }
    func logout() async throws {}
    func setKeepLogin(_ keep: Bool) async throws {}
}
private final class ManagerBridgeTestManager: ManagerSessionAPI {
    func login(username: String, password: String) async throws {}
    func restoreSession() async throws -> Bool { false }
    func logout() async {}
}
