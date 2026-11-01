import Foundation
import WebKit
import XCTest
@testable import TradeResearch

@MainActor
final class ManagerConnectionBridgeWebKitTests: XCTestCase, WKNavigationDelegate {
    private var loaded: XCTestExpectation?
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { loaded?.fulfill() }

    func testDeniedTargetClearsNativeIdentityAndSelectsTarget() async throws {
        let value: [String: Any] = ["username": "alice", "keep_login": true,
                                    "keycloak_issuer": "https://identity.test/realm", "keycloak_subject": "subject", "tr_identity_id": "alice-id"]
        let user = try JSONDecoder().decode(UserInfo.self, from: JSONSerialization.data(withJSONObject: value))
        let api = ManagerBridgeTestAPI(user: user)
        let session = SessionStore(api: api, managerAPI: ManagerBridgeTestManager(), bridge: { _ in true }, credentialLoader: { nil })
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
        api.user = try JSONDecoder().decode(UserInfo.self, from: JSONSerialization.data(withJSONObject: ["username": "visitor", "visitor_login": true]))
        _ = try await message(view, ["action": "capabilities"])
        let stale = try await message(view, ["action": "current"])
        XCTAssertEqual(stale["auth_state"] as? String, "unavailable")
        let blocked = try await message(view, ["action": "switch", "url": "https://test-manager.invalid:54321"])
        XCTAssertEqual(blocked["code"] as? String, "manager_session_changed")
        api.user = user
        _ = try await message(view, ["action": "capabilities"])
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

    func testSwitchChecksTargetOverHTTPBeforeSelectingIt() async throws {
        let python = "/opt/homebrew/Caskroom/miniconda/base/envs/GTHT/bin/python"
        guard FileManager.default.isExecutableFile(atPath: python) else { throw XCTSkip("GTHT Python is unavailable") }
        let serverCode = """
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
 calls = 0
 def do_GET(self):
  if self.path != '/api/session' or self.headers.get('Authorization') != 'Bearer isolated-test-token':
   self.send_response(401); self.end_headers(); return
  Handler.calls += 1
  subject = 'subject' if Handler.calls == 1 else 'different-subject'
  body=json.dumps({'username':'alice','keycloak_issuer':'https://identity.test/realm','keycloak_subject':subject,'tr_identity_id':'alice-id'}).encode()
  self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
 def log_message(self, *args): pass
server=HTTPServer(('127.0.0.1',0),Handler)
print(server.server_port, flush=True)
server.serve_forever()
"""
        let process = Process(); process.executableURL = URL(fileURLWithPath: python); process.arguments = ["-u", "-c", serverCode]
        let pipe = Pipe(); process.standardOutput = pipe; process.standardError = Pipe(); try process.run()
        defer { if process.isRunning { process.terminate(); process.waitUntilExit() } }
        var bytes = Data()
        while bytes.count < 10 {
            let chunk = try XCTUnwrap(try pipe.fileHandleForReading.read(upToCount: 1))
            if chunk.isEmpty || chunk == Data([10]) { break }
            bytes.append(chunk)
        }
        let port = try XCTUnwrap(Int(String(decoding: bytes, as: UTF8.self)))
        let target = try XCTUnwrap(URL(string: "http://127.0.0.1:\(port)"))
        ManagerSessionTokenStore.save("isolated-test-token", for: target)
        defer { ManagerSessionTokenStore.remove(for: target) }
        let value: [String: Any] = ["username": "alice", "keep_login": true,
                                    "keycloak_issuer": "https://identity.test/realm", "keycloak_subject": "subject", "tr_identity_id": "alice-id"]
        let user = try JSONDecoder().decode(UserInfo.self, from: JSONSerialization.data(withJSONObject: value))
        let session = SessionStore(api: ManagerBridgeTestAPI(user: user), managerAPI: ManagerBridgeTestManager(), bridge: { _ in true }, credentialLoader: { nil })
        let endpoint = try XCTUnwrap(ManagerConfig.shared.baseURL)
        var applied: URL?
        let content = WKUserContentController()
        content.addScriptMessageHandler(ManagerConnectionBridge(session: session, endpoint: endpoint,
            restoreDevice: { _, _ in nil }, apply: { applied = $0 }), contentWorld: .page, name: ManagerConnectionBridgeContract.messageName)
        let config = WKWebViewConfiguration(); config.websiteDataStore = .nonPersistent(); config.userContentController = content
        let view = WKWebView(frame: .zero, configuration: config); view.navigationDelegate = self
        loaded = expectation(description: "Manager test page")
        view.loadHTMLString("<html><body>Manager</body></html>", baseURL: endpoint)
        await fulfillment(of: [try XCTUnwrap(loaded)], timeout: 10)
        let capabilities = try await message(view, ["action": "capabilities"])
        XCTAssertEqual(capabilities["success"] as? Bool, true)
        let result = try await message(view, ["action": "switch", "url": target.absoluteString])
        XCTAssertEqual(result["auth_state"] as? String, "authorized")
        XCTAssertEqual(session.user?.stableIdentityID, "alice-id")
        XCTAssertEqual(applied, target)
        let changedSubject = try await message(view, ["action": "switch", "url": target.absoluteString])
        XCTAssertEqual(changedSubject["auth_state"] as? String, "unauthorized")
        XCTAssertNil(session.user)
        content.removeScriptMessageHandler(forName: ManagerConnectionBridgeContract.messageName)
    }

    func testAuthorizedSwitchClearsHostScopedCookiesBeforeApplyingTarget() async throws {
        let value: [String: Any] = ["username": "alice", "keep_login": true,
                                    "keycloak_issuer": "https://identity.test/realm", "keycloak_subject": "subject", "tr_identity_id": "alice-id"]
        let user = try JSONDecoder().decode(UserInfo.self, from: JSONSerialization.data(withJSONObject: value))
        let session = SessionStore(api: ManagerBridgeTestAPI(user: user), managerAPI: ManagerBridgeTestManager(), bridge: { _ in true }, credentialLoader: { nil })
        let endpoint = try XCTUnwrap(ManagerConfig.shared.baseURL)
        let target = try XCTUnwrap(URL(string: "https://test-manager.invalid:54321"))
        let cookie = try XCTUnwrap(HTTPCookie(properties: [.domain: "test-manager.invalid", .path: "/",
            .name: "ft-manager-session", .value: "source-cookie", .secure: "TRUE"]))
        HTTPCookieStorage.shared.setCookie(cookie)
        defer { HTTPCookieStorage.shared.deleteCookie(cookie) }
        var applied: URL?
        let content = WKUserContentController()
        content.addScriptMessageHandler(ManagerConnectionBridge(session: session, endpoint: endpoint,
            probe: { _, _, _ in .authorized(user) }, apply: { applied = $0 }),
            contentWorld: .page, name: ManagerConnectionBridgeContract.messageName)
        let config = WKWebViewConfiguration(); config.websiteDataStore = .nonPersistent(); config.userContentController = content
        let view = WKWebView(frame: .zero, configuration: config); view.navigationDelegate = self
        await config.websiteDataStore.httpCookieStore.setCookie(cookie)
        loaded = expectation(description: "Manager test page")
        view.loadHTMLString("<html><body>Manager</body></html>", baseURL: endpoint)
        await fulfillment(of: [try XCTUnwrap(loaded)], timeout: 10)
        _ = try await message(view, ["action": "capabilities"])
        let result = try await message(view, ["action": "switch", "url": target.absoluteString])
        XCTAssertEqual(result["auth_state"] as? String, "authorized")
        XCTAssertEqual(applied, target)
        XCTAssertFalse((HTTPCookieStorage.shared.cookies(for: target) ?? []).contains { $0.name == cookie.name })
        let remaining = await withCheckedContinuation { continuation in
            config.websiteDataStore.httpCookieStore.getAllCookies { continuation.resume(returning: $0) }
        }
        XCTAssertFalse(remaining.contains { $0.name == cookie.name && $0.domain == cookie.domain })
        content.removeScriptMessageHandler(forName: ManagerConnectionBridgeContract.messageName)
    }

    func testSwitchIsCancelledIfSessionIsReverifiedDuringProbe() async throws {
        let value: [String: Any] = ["username": "alice", "keycloak_issuer": "https://identity.test/realm",
                                    "keycloak_subject": "subject", "tr_identity_id": "alice-id"]
        let user = try JSONDecoder().decode(UserInfo.self, from: JSONSerialization.data(withJSONObject: value))
        let api = ManagerBridgeTestAPI(user: user)
        let session = SessionStore(api: api, managerAPI: ManagerBridgeTestManager(), bridge: { _ in true }, credentialLoader: { nil })
        let endpoint = try XCTUnwrap(ManagerConfig.shared.baseURL)
        var applied: URL?
        var resumeProbe: CheckedContinuation<ManagerConnectionBridge.ProbeResult, Never>?
        let probing = expectation(description: "target probe is pending")
        let content = WKUserContentController()
        content.addScriptMessageHandler(ManagerConnectionBridge(session: session, endpoint: endpoint, probe: { _, _, _ in
            await withCheckedContinuation { continuation in
                resumeProbe = continuation
                probing.fulfill()
            }
        }, apply: { applied = $0 }), contentWorld: .page, name: ManagerConnectionBridgeContract.messageName)
        let config = WKWebViewConfiguration(); config.websiteDataStore = .nonPersistent(); config.userContentController = content
        let view = WKWebView(frame: .zero, configuration: config); view.navigationDelegate = self
        loaded = expectation(description: "Manager test page")
        view.loadHTMLString("<html><body>Manager</body></html>", baseURL: endpoint)
        await fulfillment(of: [try XCTUnwrap(loaded)], timeout: 10)
        _ = try await message(view, ["action": "capabilities"])
        let pending = Task { try await self.message(view, ["action": "switch", "url": "https://test-manager.invalid:54321"]) }
        await fulfillment(of: [probing], timeout: 10)
        api.user = try JSONDecoder().decode(UserInfo.self, from: JSONSerialization.data(withJSONObject: ["username": "visitor", "visitor_login": true]))
        _ = try await message(view, ["action": "capabilities"])
        try XCTUnwrap(resumeProbe).resume(returning: .authorized(user))
        let result = try await pending.value
        XCTAssertEqual(result["code"] as? String, "manager_session_changed")
        XCTAssertNil(applied)
        content.removeScriptMessageHandler(forName: ManagerConnectionBridgeContract.messageName)
    }

    private func message(_ view: WKWebView, _ input: [String: Any]) async throws -> [String: Any] {
        let result = try await view.callAsyncJavaScript("return await window.webkit.messageHandlers.tradeResearchManager.postMessage(input)",
                                                       arguments: ["input": input], in: nil, contentWorld: .page)
        return try XCTUnwrap(result as? [String: Any])
    }
}

private final class ManagerBridgeTestAPI: SessionAPI {
    var user: UserInfo
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
