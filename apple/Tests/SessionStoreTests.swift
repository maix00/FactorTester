import Foundation
import XCTest
@testable import TradeResearch

@MainActor
final class SessionStoreTests: XCTestCase {
    func testLocalResearchIdentityRequiresVerifiedNonVisitorClaims() throws {
        func decode(_ value: [String: Any]) throws -> UserInfo {
            try JSONDecoder().decode(UserInfo.self, from: JSONSerialization.data(withJSONObject: value))
        }
        let base: [String: Any] = ["username": "alice", "keycloak_issuer": "https://id.example/realms/one",
                                   "keycloak_subject": "subject", "tr_identity_id": "stable"]
        XCTAssertEqual(try decode(base).localResearchIdentity?.stableID, "stable")
        for overrides: [String: Any] in [
            ["visitor_login": true], ["role": "visitor"], ["authentication": "agent"],
            ["tr_identity_id": ""], ["keycloak_subject": ""],
            ["keycloak_issuer": "https://user:password@id.example/realm"],
            ["keycloak_issuer": "file:///tmp/identity"],
        ] {
            XCTAssertNil(try decode(base.merging(overrides) { _, new in new }).localResearchIdentity)
        }
        XCTAssertNil(try decode(["username": "alice"]).localResearchIdentity)
    }

    func testLateRefreshCannotRestoreIdentityAfterLogout() async throws {
        let api = DelayedSessionAPI(user: try user(username: "alice"))
        let store = SessionStore(
            api: api, managerAPI: FakeManagerSessionAPI(), bridge: { _ in true },
            credentialLoader: { nil }
        )
        let refreshing = Task { await store.refresh() }
        await api.waitUntilRequested()
        await store.logout()
        api.complete()
        let refreshed = await refreshing.value
        XCTAssertFalse(refreshed)
        XCTAssertNil(store.user)
        XCTAssertFalse(store.isManagerLoggedIn)
    }

    func testLateManagerRestoreCannotMarkLoggedInAfterLogout() async throws {
        let api = FakeSessionAPI(user: try user(username: "alice"))
        let manager = DelayedManagerSessionAPI()
        let store = SessionStore(api: api, managerAPI: manager, bridge: { _ in true }, credentialLoader: { nil })
        let refreshing = Task { await store.refresh() }
        await manager.waitUntilRequested()
        await store.logout()
        manager.complete()
        let refreshed = await refreshing.value
        XCTAssertFalse(refreshed)
        XCTAssertNil(store.user)
        XCTAssertFalse(store.isManagerLoggedIn)
    }

    func testConcurrentWebConfirmationsCanShareTheSameIdentity() async throws {
        let fields: [String: Any] = ["username": "alice", "keep_login": true,
            "keycloak_issuer": "https://id.example/realms/a", "keycloak_subject": "subject", "tr_identity_id": "stable"]
        let verified = try JSONDecoder().decode(UserInfo.self, from: JSONSerialization.data(withJSONObject: fields))
        let api = ConcurrentSessionAPI(user: verified)
        let store = SessionStore(api: api, managerAPI: FakeManagerSessionAPI(), bridge: { _ in true }, credentialLoader: { nil })
        let first = Task { await store.confirmWebIdentity() }
        let second = Task { await store.confirmWebIdentity() }
        while api.pending.count < 2 { await Task.yield() }
        api.completeFirst()
        let firstResult = await first.value
        api.completeFirst()
        let secondResult = await second.value
        XCTAssertTrue(firstResult)
        XCTAssertTrue(secondResult)
    }

    func testWebIdentityBridgesChangedSessionOnlyOnce() async throws {
        let fields: [String: Any] = ["username": "alice", "keep_login": true,
            "keycloak_issuer": "https://id.example/realms/a", "keycloak_subject": "subject", "tr_identity_id": "stable"]
        let verified = try JSONDecoder().decode(UserInfo.self, from: JSONSerialization.data(withJSONObject: fields))
        let first = expectation(description: "first verified session")
        let second = expectation(description: "updated verified session")
        var token = "first"
        var calls = 0
        let store = SessionStore(api: FakeSessionAPI(user: verified), managerAPI: FakeManagerSessionAPI(),
            bridge: { _ in
                calls += 1
                if calls == 1 { first.fulfill() }
                if calls == 2 { second.fulfill() }
                return true
            }, credentialLoader: { nil }, managerTokenReader: { _ in token })
        let firstConfirmed = await store.confirmWebIdentity()
        XCTAssertTrue(firstConfirmed)
        await fulfillment(of: [first], timeout: 2)
        let repeatedConfirmed = await store.confirmWebIdentity()
        XCTAssertTrue(repeatedConfirmed)
        for _ in 0..<10 { await Task.yield() }
        XCTAssertEqual(calls, 1)
        token = "second"
        let changedConfirmed = await store.confirmWebIdentity()
        XCTAssertTrue(changedConfirmed)
        await fulfillment(of: [second], timeout: 2)
        XCTAssertEqual(calls, 2)
    }

    func testWebIdentityConfirmationRequiresVerifiedIdentityAndDoesNotReplayCredentials() async throws {
        let fields: [String: Any] = ["username": "alice", "keep_login": true,
            "keycloak_issuer": "https://id.example/realms/a", "keycloak_subject": "subject",
            "tr_identity_id": "stable-alice"]
        let verified = try JSONDecoder().decode(UserInfo.self, from: JSONSerialization.data(withJSONObject: fields))
        let api = FakeSessionAPI(user: verified)
        let store = SessionStore(api: api, managerAPI: FakeManagerSessionAPI(), bridge: { _ in true },
                                 credentialLoader: { SavedSessionCredentials(username: "alice", password: "secret", serverURL: nil) })
        let accepted = await store.confirmWebIdentity()
        XCTAssertTrue(accepted)
        XCTAssertEqual(store.user?.localResearchIdentity?.stableID, "stable-alice")
        XCTAssertEqual(api.events, ["me"])

        let legacy = FakeSessionAPI(user: try user(username: "alice"))
        let unverifiedStore = SessionStore(api: legacy, managerAPI: FakeManagerSessionAPI(), bridge: { _ in true })
        let rejected = await unverifiedStore.confirmWebIdentity()
        XCTAssertFalse(rejected)
        XCTAssertNil(unverifiedStore.user)
        XCTAssertEqual(legacy.events, ["me"])
    }

    func testAdoptingManagerSessionCannotChangeStableUser() async throws {
        func verified(_ stable: String, subject: String = "subject", issuer: String = "https://id.example/realms/a") throws -> UserInfo {
            let fields: [String: Any] = ["username": "alice", "keep_login": true,
                "keycloak_issuer": issuer, "keycloak_subject": subject, "tr_identity_id": stable]
            return try JSONDecoder().decode(UserInfo.self, from: JSONSerialization.data(withJSONObject: fields))
        }
        let alice = try verified("stable-alice")
        let store = SessionStore(api: FakeSessionAPI(user: alice), managerAPI: FakeManagerSessionAPI(), bridge: { _ in true })
        let confirmed = await store.confirmWebIdentity()
        XCTAssertTrue(confirmed)
        let original = alice.localResearchIdentity
        XCTAssertFalse(store.adoptManagerSession(expected: original, candidate: try verified("different")))
        XCTAssertFalse(store.adoptManagerSession(expected: original, candidate: try verified("stable-alice", subject: "different")))
        XCTAssertFalse(store.adoptManagerSession(expected: original, candidate: try verified("stable-alice", subject: "different", issuer: "https://id.example/realms/a/")))
        XCTAssertFalse(store.adoptManagerSession(expected: original, candidate: try verified("stable-alice", issuer: "https://other.example/realms/a")))
        XCTAssertEqual(store.user?.stableIdentityID, "stable-alice")
        XCTAssertTrue(store.adoptManagerSession(expected: original, candidate: nil))
        XCTAssertNil(store.user)
        XCTAssertFalse(store.adoptManagerSession(expected: original, candidate: alice))
    }

    func testManagerChangeRequiresMatchingVerifiedIdentityWithoutPasswordLogin() async throws {
        let fields: [String: Any] = ["username": "alice", "keep_login": true,
            "keycloak_issuer": "https://id.example/realms/a", "keycloak_subject": "subject",
            "tr_identity_id": "stable-alice"]
        let verified = try JSONDecoder().decode(UserInfo.self, from: JSONSerialization.data(withJSONObject: fields))
        let api = FakeSessionAPI(user: verified)
        let store = SessionStore(api: api, managerAPI: FakeManagerSessionAPI(), bridge: { _ in true },
                                 credentialLoader: { SavedSessionCredentials(username: "alice", password: "secret", serverURL: nil) })
        let original = try XCTUnwrap(verified.localResearchIdentity)
        let mismatched = await store.validateManagerChange(expectedIdentity: LocalResearchIdentity(
            issuer: original.issuer, subject: original.subject, stableID: "another-user"))
        XCTAssertFalse(mismatched)
        XCTAssertNil(store.user)
        XCTAssertEqual(api.events, ["me"])
        let differentSubject = await store.validateManagerChange(expectedIdentity: LocalResearchIdentity(
            issuer: original.issuer + "/", subject: "different-subject", stableID: original.stableID))
        XCTAssertFalse(differentSubject)
        XCTAssertNil(store.user)
        let differentIssuer = await store.validateManagerChange(expectedIdentity: LocalResearchIdentity(
            issuer: "https://other.example/realms/a", subject: original.subject, stableID: original.stableID))
        XCTAssertFalse(differentIssuer)
        XCTAssertNil(store.user)
        let matched = await store.validateManagerChange(expectedIdentity: original)
        XCTAssertTrue(matched)
        XCTAssertEqual(store.user?.username, "alice")
        XCTAssertEqual(api.events, ["me", "me", "me", "me"])
    }

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
            },
            // This fixture represents a private/internal Manager.  The real
            // default restorer probes the baked public endpoint, which would
            // make the test depend on the machine's current network.
            managerDeviceSessionRestorer: { _ in .notRequired }
        )

        let succeeded = await store.refresh()

        XCTAssertTrue(succeeded)
        XCTAssertTrue(store.isLoggedIn)
        XCTAssertTrue(store.isManagerLoggedIn)
        XCTAssertEqual(manager.restoreCount, 1)
        XCTAssertEqual(manager.loginCount, 1)
    }

    func testRefreshRepairsExpiredPublicManagerSessionWithBoundDevice() async throws {
        let api = FakeSessionAPI(user: try user(username: "alice"))
        let manager = FakeManagerSessionAPI(restoreResult: false)
        var deviceRestoreCount = 0
        let store = SessionStore(
            api: api,
            managerAPI: manager,
            bridge: { _ in true },
            credentialLoader: {
                SavedSessionCredentials(
                    username: "alice",
                    password: "must-not-be-used",
                    serverURL: nil
                )
            },
            managerDeviceSessionRestorer: { _ in
                deviceRestoreCount += 1
                return .authenticated(username: "alice")
            }
        )

        let succeeded = await store.refresh()

        XCTAssertTrue(succeeded)
        XCTAssertTrue(store.isManagerLoggedIn)
        XCTAssertEqual(deviceRestoreCount, 1)
        XCTAssertEqual(manager.loginCount, 0)
    }

    func testPublicDeviceSessionCannotSwitchTheCurrentAccount() async throws {
        let api = FakeSessionAPI(user: try user(username: "alice"))
        let manager = FakeManagerSessionAPI(restoreResult: false)
        let store = SessionStore(
            api: api,
            managerAPI: manager,
            bridge: { _ in true },
            credentialLoader: {
                SavedSessionCredentials(
                    username: "alice",
                    password: "must-not-be-used",
                    serverURL: nil
                )
            },
            managerDeviceSessionRestorer: { _ in
                .authenticated(username: "bob")
            }
        )

        let succeeded = await store.refresh()

        XCTAssertTrue(succeeded)
        XCTAssertFalse(store.isManagerLoggedIn)
        XCTAssertEqual(manager.loginCount, 0)
        XCTAssertEqual(
            store.lastError,
            L10n.text("当前设备绑定的用户与已登录用户不一致，已拒绝切换账号。")
        )
    }

    func testDeviceProofWithoutOIDCCallbackDoesNotRestoreManagerOrUsePassword() async throws {
        let api = FakeSessionAPI(user: try user(username: "alice"))
        let manager = FakeManagerSessionAPI(restoreResult: false)
        let store = SessionStore(
            api: api, managerAPI: manager, bridge: { _ in true },
            credentialLoader: { SavedSessionCredentials(username: "alice", password: "unused", serverURL: nil) },
            managerDeviceSessionRestorer: { _ in .requiresWebLogin }
        )
        let succeeded = await store.refresh()
        XCTAssertTrue(succeeded)
        XCTAssertFalse(store.isManagerLoggedIn)
        XCTAssertEqual(manager.loginCount, 0)
    }

    func testFailedPublicDeviceRestoreDoesNotFallBackToPassword() async throws {
        let api = FakeSessionAPI(user: try user(username: "alice"))
        let manager = FakeManagerSessionAPI(restoreResult: false)
        let store = SessionStore(
            api: api,
            managerAPI: manager,
            bridge: { _ in true },
            credentialLoader: {
                SavedSessionCredentials(
                    username: "alice",
                    password: "must-not-be-used",
                    serverURL: nil
                )
            },
            managerDeviceSessionRestorer: { _ in
                throw APIError.unauthorized("device is not approved")
            }
        )

        let succeeded = await store.refresh()

        XCTAssertTrue(succeeded)
        XCTAssertFalse(store.isManagerLoggedIn)
        XCTAssertEqual(manager.loginCount, 0)
        XCTAssertEqual(store.lastError, "device is not approved")
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

@MainActor
private final class DelayedSessionAPI: SessionAPI {
    private let user: UserInfo
    private var pending: CheckedContinuation<UserInfo, Never>?
    private var onRequest: CheckedContinuation<Void, Never>?
    private var requested = false

    init(user: UserInfo) { self.user = user }
    func waitUntilRequested() async {
        if requested { return }
        await withCheckedContinuation { onRequest = $0 }
    }
    func complete() { pending?.resume(returning: user); pending = nil }
    func me() async throws -> UserInfo {
        await withCheckedContinuation { continuation in
            pending = continuation
            requested = true
            onRequest?.resume()
            onRequest = nil
        }
    }
    func login(username: String, password: String) async throws -> AuthResponse {
        throw APIError.unauthorized("unauthorized")
    }
    func register(username: String, password: String, organizationId: String) async throws -> AuthResponse {
        throw APIError.unauthorized("unauthorized")
    }
    func logout() async throws {}
    func setKeepLogin(_ keep: Bool) async throws {}
}

@MainActor
private final class DelayedManagerSessionAPI: ManagerSessionAPI {
    private var pending: CheckedContinuation<Bool, Never>?
    private var onRequest: CheckedContinuation<Void, Never>?
    private var requested = false
    func waitUntilRequested() async {
        if requested { return }
        await withCheckedContinuation { onRequest = $0 }
    }
    func complete() { pending?.resume(returning: true); pending = nil }
    func restoreSession() async throws -> Bool {
        await withCheckedContinuation { continuation in
            pending = continuation
            requested = true
            onRequest?.resume()
            onRequest = nil
        }
    }
    func login(username: String, password: String) async throws {}
    func logout() async {}
}

@MainActor
private final class ConcurrentSessionAPI: SessionAPI {
    let user: UserInfo
    var pending: [CheckedContinuation<UserInfo, Never>] = []
    init(user: UserInfo) { self.user = user }
    func me() async throws -> UserInfo { await withCheckedContinuation { pending.append($0) } }
    func completeFirst() { pending.removeFirst().resume(returning: user) }
    func login(username: String, password: String) async throws -> AuthResponse { throw APIError.unauthorized("no") }
    func register(username: String, password: String, organizationId: String) async throws -> AuthResponse { throw APIError.unauthorized("no") }
    func logout() async throws {}
    func setKeepLogin(_ keep: Bool) async throws {}
}
