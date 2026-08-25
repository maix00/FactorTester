import XCTest
@testable import FTClient

final class ResearchFactorSetMemberListTests: XCTestCase {
    func testMemberPageAlwaysUsesNativeCLIAndFrozenTarget() {
        let target = "factor-set:v2:" + String(repeating: "a", count: 43)
        XCTAssertEqual(
            ResearchFactorSetMemberList.commandArguments(
                targetRef: target, offset: 50, limit: 50
            ),
            [
                "client", "profile", "factor-worktree", "factor-set",
                "members", "--target-ref", target,
                "--offset", "50", "--limit", "50", "--json",
            ]
        )
    }

    @MainActor
    func testIdenticalMemberPagesShareOneInFlightLoad() async throws {
        let cache = ResearchFactorSetMemberPageCache()
        var loadCount = 0
        let loader: @MainActor () async throws -> [String: Any] = {
            loadCount += 1
            try await Task.sleep(nanoseconds: 10_000_000)
            return ["member_count": 4]
        }

        async let first = cache.value(
            targetRef: "factor-set:v2:" + String(repeating: "a", count: 43),
            offset: 0, limit: 50,
            loader: loader
        )
        async let second = cache.value(
            targetRef: "factor-set:v2:" + String(repeating: "a", count: 43),
            offset: 0, limit: 50,
            loader: loader
        )
        let values = try await [first, second]

        XCTAssertEqual(loadCount, 1)
        XCTAssertEqual(values.compactMap { $0["member_count"] as? Int }, [4, 4])
    }

    @MainActor
    func testCompletedMemberPageIsReused() async throws {
        let cache = ResearchFactorSetMemberPageCache()
        var loadCount = 0
        let loader: @MainActor () async throws -> [String: Any] = {
            loadCount += 1
            return ["member_count": 4]
        }

        _ = try await cache.value(
            targetRef: "factor-set:v2:" + String(repeating: "a", count: 43),
            offset: 0, limit: 50,
            loader: loader
        )
        _ = try await cache.value(
            targetRef: "factor-set:v2:" + String(repeating: "a", count: 43),
            offset: 0, limit: 50,
            loader: loader
        )

        XCTAssertEqual(loadCount, 1)
    }
}
