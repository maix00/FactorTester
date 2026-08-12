import Foundation
import XCTest
@testable import FTClient

@MainActor
final class SessionStoreTests: XCTestCase {
    func testNilUsernameIsNotAnAuthenticatedIdentity() async throws {
        let api = FakeSessionAPI(user: try user(username: nil))
        let store = SessionStore(
            api: api, managerAPI: FakeManagerSessionAPI(), bridge: { _ in true }
        )

        await store.refresh()

        XCTAssertNotNil(store.user)
        XCTAssertFalse(store.isLoggedIn)
        XCTAssertFalse(ResearchSessionAccess.canLoad(user: store.user))
    }

    func testLoginPersistsSessionBeforeRefreshingAndBridgingCLI() async throws {
        let api = FakeSessionAPI(user: try user(username: "alice"))
        let store = SessionStore(
            api: api,
            managerAPI: FakeManagerSessionAPI(),
            bridge: { principal in
                api.events.append("bridge:\(principal)")
                return true
            },
            credentialSaver: { username, password in
                api.events.append("save:\(username):\(password)")
                return true
            }
        )

        let succeeded = await store.login(
            username: "alice",
            password: "password"
        )

        XCTAssertTrue(succeeded)
        XCTAssertTrue(store.isLoggedIn)
        XCTAssertEqual(
            api.events,
            ["login", "keep:true", "me", "save:alice:password", "bridge:alice"]
        )
    }

    func testLoginReportsCredentialPersistenceFailureWithoutLoggingOut() async throws {
        let api = FakeSessionAPI(user: try user(username: "alice"))
        let store = SessionStore(
            api: api,
            managerAPI: FakeManagerSessionAPI(),
            bridge: { _ in true },
            credentialSaver: { _, _ in false }
        )

        let succeeded = await store.login(username: "alice", password: "secret")

        XCTAssertTrue(succeeded)
        XCTAssertTrue(store.isLoggedIn)
        XCTAssertEqual(
            store.lastError,
            L10n.text("登录成功，但本机凭证未能保存；重启后可能需要重新登录")
        )
    }

    func testLogoutClearsVisibleIdentityBeforeRemoteCleanup() async throws {
        let api = FakeSessionAPI(user: try user(username: "alice"))
        let store = SessionStore(
            api: api, managerAPI: FakeManagerSessionAPI(), bridge: { _ in true }
        )
        await store.refresh()
        XCTAssertTrue(store.isLoggedIn)

        await store.logout()

        XCTAssertNil(store.user)
        XCTAssertFalse(store.isLoggedIn)
    }

    func testRegistrationUsesTheSamePersistentSessionFinalization() async throws {
        let api = FakeSessionAPI(user: try user(username: "alice"))
        let store = SessionStore(
            api: api,
            managerAPI: FakeManagerSessionAPI(),
            bridge: { principal in
                api.events.append("bridge:\(principal)")
                return true
            },
            credentialSaver: { username, password in
                api.events.append("save:\(username):\(password)")
                return true
            }
        )

        let succeeded = await store.register(
            username: "alice",
            password: "password",
            organizationId: "org"
        )

        XCTAssertTrue(succeeded)
        XCTAssertTrue(store.isLoggedIn)
        XCTAssertEqual(
            api.events,
            ["register", "keep:true", "me", "save:alice:password", "bridge:alice"]
        )
    }

    func testLoginFailsClosedWhenPersistentSessionCannotBeConfirmed() async throws {
        let api = FakeSessionAPI(
            user: try user(username: "alice", keepLogin: false),
            keepLoginError: APIError.transport("keep-login unavailable")
        )
        let store = SessionStore(
            api: api, managerAPI: FakeManagerSessionAPI(), bridge: { _ in true }
        )

        let succeeded = await store.login(
            username: "alice",
            password: "password"
        )

        XCTAssertFalse(succeeded)
        XCTAssertFalse(store.isLoggedIn)
        XCTAssertNotNil(store.lastError)
        XCTAssertEqual(api.events, ["login", "keep:true", "me"])
    }

    func testSuperAdminLoginAlsoAuthenticatesManager() async throws {
        let api = FakeSessionAPI(
            user: try user(username: "root", role: "super_admin")
        )
        let manager = FakeManagerSessionAPI()
        let store = SessionStore(
            api: api,
            managerAPI: manager,
            bridge: { _ in true }
        )

        let succeeded = await store.login(username: "root", password: "secret")
        XCTAssertTrue(succeeded)
        XCTAssertTrue(store.isManagerLoggedIn)
        XCTAssertEqual(manager.loginCount, 1)
    }

    func testRegularUserAuthenticatesUnifiedManagerGateway() async throws {
        let api = FakeSessionAPI(user: try user(username: "alice"))
        let manager = FakeManagerSessionAPI()
        let store = SessionStore(
            api: api,
            managerAPI: manager,
            bridge: { _ in true }
        )

        let succeeded = await store.login(username: "alice", password: "secret")
        XCTAssertTrue(succeeded)
        XCTAssertTrue(store.isManagerLoggedIn)
        XCTAssertEqual(manager.loginCount, 1)
    }

    func testRefreshRepairsExpiredManagerSessionForRegularUser() async throws {
        let api = FakeSessionAPI(user: try user(username: "alice"))
        let manager = FakeManagerSessionAPI(restoreResult: false)
        let store = SessionStore(
            api: api,
            managerAPI: manager,
            bridge: { _ in true },
            credentialLoader: {
                SavedSessionCredentials(
                    username: "alice",
                    password: "secret",
                    serverURL: nil
                )
            }
        )

        let succeeded = await store.refresh()

        XCTAssertTrue(succeeded)
        XCTAssertTrue(store.isLoggedIn)
        XCTAssertTrue(store.isManagerLoggedIn)
        XCTAssertEqual(manager.restoreCount, 1)
        XCTAssertEqual(manager.loginCount, 1)
    }

    private func user(
        username: String?,
        role: String? = nil,
        keepLogin: Bool = true
    ) throws -> UserInfo {
        let usernameValue: Any = username.map { $0 as Any } ?? NSNull()
        let value: [String: Any] = [
            "username": usernameValue,
            "is_admin": false,
            "is_developer": false,
            "keep_login": keepLogin,
        ]
        var mutableValue = value
        if let role { mutableValue["role"] = role }
        return try JSONDecoder().decode(
            UserInfo.self,
            from: JSONSerialization.data(withJSONObject: mutableValue)
        )
    }
}

private final class FakeManagerSessionAPI: ManagerSessionAPI {
    var loginCount = 0
    var restoreCount = 0
    let restoreResult: Bool

    init(restoreResult: Bool = true) {
        self.restoreResult = restoreResult
    }

    func login(username: String, password: String) async throws {
        loginCount += 1
    }

    func restoreSession() async throws -> Bool {
        restoreCount += 1
        return restoreResult
    }

    func logout() async {}
}

private final class FakeSessionAPI: SessionAPI {
    var events: [String] = []
    let user: UserInfo
    let keepLoginError: Error?

    init(user: UserInfo, keepLoginError: Error? = nil) {
        self.user = user
        self.keepLoginError = keepLoginError
    }

    func me() async throws -> UserInfo {
        events.append("me")
        return user
    }

    func login(
        username: String,
        password: String
    ) async throws -> AuthResponse {
        events.append("login")
        return AuthResponse(
            success: true,
            error: nil,
            username: username,
            alias: username,
            role: "user",
            isAdmin: false
        )
    }

    func register(
        username: String,
        password: String,
        organizationId: String
    ) async throws -> AuthResponse {
        events.append("register")
        return AuthResponse(
            success: true,
            error: nil,
            username: username,
            alias: username,
            role: "user",
            isAdmin: false
        )
    }

    func logout() async throws {
        events.append("logout")
    }

    func setKeepLogin(_ keep: Bool) async throws {
        events.append("keep:\(keep)")
        if let keepLoginError { throw keepLoginError }
    }
}
