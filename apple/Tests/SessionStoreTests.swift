import Foundation
import XCTest
@testable import FTClient

@MainActor
final class SessionStoreTests: XCTestCase {
    func testNilUsernameIsNotAnAuthenticatedIdentity() async throws {
        let api = FakeSessionAPI(user: try user(username: nil))
        let store = SessionStore(api: api, bridge: { _ in true })

        await store.refresh()

        XCTAssertNotNil(store.user)
        XCTAssertFalse(store.isLoggedIn)
        XCTAssertFalse(ResearchSessionAccess.canLoad(user: store.user))
    }

    func testLoginPersistsSessionBeforeRefreshingAndBridgingCLI() async throws {
        let api = FakeSessionAPI(user: try user(username: "alice"))
        let store = SessionStore(api: api, bridge: { principal in
            api.events.append("bridge:\(principal)")
            return true
        })

        let succeeded = await store.login(
            username: "alice",
            password: "password"
        )

        XCTAssertTrue(succeeded)
        XCTAssertTrue(store.isLoggedIn)
        XCTAssertEqual(
            api.events,
            ["login", "keep:true", "me", "bridge:alice"]
        )
    }

    func testLogoutClearsVisibleIdentityBeforeRemoteCleanup() async throws {
        let api = FakeSessionAPI(user: try user(username: "alice"))
        let store = SessionStore(api: api, bridge: { _ in true })
        await store.refresh()
        XCTAssertTrue(store.isLoggedIn)

        await store.logout()

        XCTAssertNil(store.user)
        XCTAssertFalse(store.isLoggedIn)
    }

    func testRegistrationUsesTheSamePersistentSessionFinalization() async throws {
        let api = FakeSessionAPI(user: try user(username: "alice"))
        let store = SessionStore(api: api, bridge: { principal in
            api.events.append("bridge:\(principal)")
            return true
        })

        let succeeded = await store.register(
            username: "alice",
            password: "password",
            organizationId: "org"
        )

        XCTAssertTrue(succeeded)
        XCTAssertTrue(store.isLoggedIn)
        XCTAssertEqual(
            api.events,
            ["register", "keep:true", "me", "bridge:alice"]
        )
    }

    private func user(username: String?) throws -> UserInfo {
        let usernameValue: Any = username.map { $0 as Any } ?? NSNull()
        let value: [String: Any] = [
            "username": usernameValue,
            "is_admin": false,
            "is_developer": false,
            "keep_login": true,
        ]
        return try JSONDecoder().decode(
            UserInfo.self,
            from: JSONSerialization.data(withJSONObject: value)
        )
    }
}

private final class FakeSessionAPI: SessionAPI {
    var events: [String] = []
    let user: UserInfo

    init(user: UserInfo) {
        self.user = user
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
    }
}
