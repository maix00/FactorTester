#if os(macOS)
import Foundation
import WebKit
import XCTest
@testable import FTClient

@MainActor
final class LocalResearchBridgeWebKitTests: XCTestCase, WKNavigationDelegate {
    private var loaded: XCTestExpectation?
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { loaded?.fulfill() }

    func testWebKitBridgeCreatesAndReadsActualLocalResearch() async throws {
        let python = "/opt/homebrew/Caskroom/miniconda/base/envs/GTHT/bin/python"
        guard FileManager.default.isExecutableFile(atPath: python) else { throw XCTSkip("GTHT Python is unavailable") }
        let repo = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("tr-native-bridge-\(UUID().uuidString)")
        let oldRoot = getenv("TRADERESEARCH_CLIENT_ROOT").map { String(cString: $0) }
        let oldPythonPath = getenv("PYTHONPATH").map { String(cString: $0) }
        setenv("TRADERESEARCH_CLIENT_ROOT", root.path, 1)
        setenv("PYTHONPATH", repo.path, 1)
        defer {
            if let oldRoot { setenv("TRADERESEARCH_CLIENT_ROOT", oldRoot, 1) } else { unsetenv("TRADERESEARCH_CLIENT_ROOT") }
            if let oldPythonPath { setenv("PYTHONPATH", oldPythonPath, 1) } else { unsetenv("PYTHONPATH") }
            try? FileManager.default.removeItem(at: root)
        }
        let sessionJSON: [String: Any] = ["username": "alice", "keep_login": true,
            "keycloak_issuer": "https://identity.test/realm", "keycloak_subject": "subject", "tr_identity_id": "stable-alice"]
        let user = try JSONDecoder().decode(UserInfo.self, from: JSONSerialization.data(withJSONObject: sessionJSON))
        let api = LocalResearchSessionAPI(user: user)
        let store = SessionStore(api: api, managerAPI: LocalResearchManagerAPI(), bridge: { _ in true }, credentialLoader: { nil })
        let endpoint = try XCTUnwrap(ManagerConfig.shared.baseURL)
        let controller = WKUserContentController()
        var runnerCalled = false
        controller.addScriptMessageHandler(LocalResearchBridge(session: store, endpoint: endpoint, runner: { envelope in
            runnerCalled = true
            return try await ReleaseCommand.runObject(["-m", "tools.cli.app", "client", "local-research-request"],
                                                      executable: python, stdinJSON: envelope, timeout: .seconds(8))
        }), contentWorld: .page, name: LocalResearchBridgeContract.messageName)
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.userContentController = controller
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = self
        loaded = expectation(description: "local test document")
        view.loadHTMLString("<html><body>Research</body></html>", baseURL: endpoint)
        await fulfillment(of: [try XCTUnwrap(loaded)], timeout: 10)
        let capability = try await message(view, ["action": "capabilities"])
        guard capability["success"] as? Bool == true else {
            XCTFail("Bridge handshake failed: \(capability["code"] as? String ?? "unknown"); runner called: \(runnerCalled)")
            return
        }
        XCTAssertTrue((capability["actions"] as? [String])?.contains("publish_report") == true)
        XCTAssertTrue((capability["actions"] as? [String])?.contains("import_research") == true)
        XCTAssertNil(capability["manager"])
        let created = try await message(view, ["action": "create", "profile_id": "self", "title": "WK test", "description": "", "operation_id": "test-operation"])
        let row = try XCTUnwrap(created["research"] as? [String: Any])
        XCTAssertEqual(row["title"] as? String, "WK test")
        let listed = try await message(view, ["action": "list", "profile_id": "self", "limit": 20, "offset": 0])
        XCTAssertEqual((listed["researches"] as? [[String: Any]])?.count, 1)
        let researchID = try XCTUnwrap(row["research_id"] as? String)
        let report = try await message(view, ["action": "create_report", "profile_id": "self", "research_id": researchID,
                                              "title": "WK report", "operation_id": "report-operation"])
        let reportRow = try XCTUnwrap(report["report"] as? [String: Any])
        let reports = try await message(view, ["action": "list_profile_reports", "profile_id": "self", "limit": 20, "offset": 0,
                                                "expected_revision": NSNull()])
        let result = try XCTUnwrap((reports["reports"] as? [[String: Any]])?.first)
        XCTAssertEqual(result["report_id"] as? String, reportRow["report_id"] as? String)
        XCTAssertEqual((result["research"] as? [String: Any])?["research_id"] as? String, researchID)
        api.user = try JSONDecoder().decode(UserInfo.self, from: JSONSerialization.data(withJSONObject: ["username": "visitor", "visitor_login": true]))
        let rejected = try await message(view, ["action": "capabilities"])
        XCTAssertEqual(rejected["success"] as? Bool, false)
        let afterRejection = try await message(view, ["action": "list", "profile_id": "self", "limit": 20, "offset": 0])
        XCTAssertEqual(afterRejection["success"] as? Bool, false)
        controller.removeScriptMessageHandler(forName: LocalResearchBridgeContract.messageName)
    }

    private func message(_ view: WKWebView, _ input: [String: Any]) async throws -> [String: Any] {
        let value = try await view.callAsyncJavaScript(
            "return await window.webkit.messageHandlers.tradeResearchLocalResearch.postMessage(input)",
            arguments: ["input": input], in: nil, contentWorld: .page
        )
        return try XCTUnwrap(value as? [String: Any])
    }
}

private final class LocalResearchSessionAPI: SessionAPI {
    var user: UserInfo
    init(user: UserInfo) { self.user = user }
    func me() async throws -> UserInfo { user }
    func login(username: String, password: String) async throws -> AuthResponse { throw APIError.unauthorized("no") }
    func register(username: String, password: String, organizationId: String) async throws -> AuthResponse { throw APIError.unauthorized("no") }
    func logout() async throws {}
    func setKeepLogin(_ keep: Bool) async throws {}
}

private final class LocalResearchManagerAPI: ManagerSessionAPI {
    func login(username: String, password: String) async throws {}
    func restoreSession() async throws -> Bool { false }
    func logout() async {}
}
#endif
