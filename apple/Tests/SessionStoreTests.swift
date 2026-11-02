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
            api: api, bridge: { _ in true }
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

    func testConcurrentWebConfirmationsCanShareTheSameIdentity() async throws {
        let fields: [String: Any] = ["username": "alice", "keep_login": true,
            "keycloak_issuer": "https://id.example/realms/a", "keycloak_subject": "subject", "tr_identity_id": "stable"]
        let verified = try JSONDecoder().decode(UserInfo.self, from: JSONSerialization.data(withJSONObject: fields))
        let api = ConcurrentSessionAPI(user: verified)
        let store = SessionStore(api: api, bridge: { _ in true })
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
        let store = SessionStore(api: FakeSessionAPI(user: verified),
            bridge: { _ in
                calls += 1
                if calls == 1 { first.fulfill() }
                if calls == 2 { second.fulfill() }
                return true
            }, managerTokenReader: { _ in token })
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
        let store = SessionStore(api: api, bridge: { _ in true })
        let accepted = await store.confirmWebIdentity()
        XCTAssertTrue(accepted)
        XCTAssertEqual(store.user?.localResearchIdentity?.stableID, "stable-alice")
        XCTAssertEqual(api.events, ["me"])

        let legacy = FakeSessionAPI(user: try user(username: "alice", verified: false))
        let unverifiedStore = SessionStore(api: legacy, bridge: { _ in true })
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
        let store = SessionStore(api: FakeSessionAPI(user: alice), bridge: { _ in true })
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
        let store = SessionStore(api: api, bridge: { _ in true })
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
            api: api, bridge: { _ in true }
        )

        await store.refresh()

        XCTAssertNil(store.user)
        XCTAssertFalse(store.isLoggedIn)
        XCTAssertFalse(ResearchSessionAccess.canLoad(user: store.user))
    }

    func testRefreshUsesOnlyTheVerifiedManagerSession() async throws {
        let api = FakeSessionAPI(user: try user(username: "alice", keepLogin: false))
        let store = SessionStore(api: api, bridge: { _ in true })
        let accepted = await store.refresh()
        XCTAssertTrue(accepted)
        XCTAssertTrue(store.isManagerLoggedIn)
        XCTAssertEqual(api.events, ["me"])
        api.failure = APIError.transport("offline")
        let offline = await store.refresh()
        XCTAssertTrue(offline)
        XCTAssertEqual(store.user?.username, "alice")
        api.failure = APIError.unauthorized("revoked")
        let denied = await store.refresh()
        XCTAssertFalse(denied)
        XCTAssertNil(store.user)
        XCTAssertFalse(store.isManagerLoggedIn)
    }

    func testRejectedWebHandshakeClearsPreviousVerifiedIdentity() async throws {
        let api = FakeSessionAPI(user: try user(username: "alice"))
        let store = SessionStore(api: api, bridge: { _ in true })
        let first = await store.confirmWebIdentity()
        XCTAssertTrue(first)
        api.failure = APIError.unauthorized("revoked")
        let revoked = await store.confirmWebIdentity()
        XCTAssertFalse(revoked)
        XCTAssertNil(store.user)
    }

    func testEmptySessionInvalidatesOtherPendingRefreshes() async throws {
        let api = ConcurrentSessionAPI(user: try user(username: "alice"))
        let store = SessionStore(api: api, bridge: { _ in true })
        let first = Task { await store.refresh() }
        while api.pending.isEmpty { await Task.yield() }
        let stale = Task { await store.refresh() }
        while api.pending.count < 2 { await Task.yield() }
        api.completeFirst(try user(username: nil))
        let denied = await first.value
        api.completeFirst()
        let late = await stale.value
        XCTAssertFalse(denied)
        XCTAssertFalse(late)
        XCTAssertNil(store.user)
    }

    func testLateClientBridgeCannotRestoreIdentityAfterLogout() async throws {
        let requested = expectation(description: "bridge entered")
        var continuation: CheckedContinuation<Bool, Never>?
        let store = SessionStore(api: FakeSessionAPI(user: try user(username: "alice")),
            bridge: { _ in
                requested.fulfill()
                return await withCheckedContinuation { continuation = $0 }
            }, managerTokenReader: { _ in "session-token" })
        let refreshing = Task { await store.refresh() }
        await fulfillment(of: [requested], timeout: 2)
        let loggingOut = Task { await store.logout() }
        while store.user != nil { await Task.yield() }
        continuation?.resume(returning: true)
        let refreshed = await refreshing.value
        await loggingOut.value
        XCTAssertFalse(refreshed)
        XCTAssertNil(store.user)
    }

    private func user(username: String?, role: String? = nil, keepLogin: Bool = true,
                      verified: Bool = true) throws -> UserInfo {
        var value: [String: Any] = ["username": username.map { $0 as Any } ?? NSNull(), "keep_login": keepLogin]
        if let role { value["role"] = role }
        if verified {
            value["keycloak_issuer"] = "https://identity.example/realms/test"
            value["keycloak_subject"] = "subject-alice"
            value["tr_identity_id"] = "stable-alice"
        }
        return try JSONDecoder().decode(UserInfo.self, from: JSONSerialization.data(withJSONObject: value))
    }
}

private final class FakeSessionAPI: SessionAPI {
    var events: [String] = []
    let user: UserInfo
    var failure: Error?
    init(user: UserInfo) { self.user = user }
    func me() async throws -> UserInfo {
        events.append("me")
        if let failure { throw failure }
        return user
    }
    func logout() async throws { events.append("logout") }
}

@MainActor
private final class DelayedSessionAPI: SessionAPI {
    let user: UserInfo
    private var requested = false
    private var pending: CheckedContinuation<UserInfo, Never>?
    init(user: UserInfo) { self.user = user }
    func waitUntilRequested() async { while !requested { await Task.yield() } }
    func complete() { pending?.resume(returning: user); pending = nil }
    func me() async throws -> UserInfo {
        requested = true
        return await withCheckedContinuation { pending = $0 }
    }
    func logout() async throws {}
}

@MainActor
private final class ConcurrentSessionAPI: SessionAPI {
    let user: UserInfo
    var pending: [CheckedContinuation<UserInfo, Never>] = []
    init(user: UserInfo) { self.user = user }
    func me() async throws -> UserInfo { await withCheckedContinuation { pending.append($0) } }
    func completeFirst(_ candidate: UserInfo? = nil) { pending.removeFirst().resume(returning: candidate ?? user) }
    func logout() async throws {}
}
