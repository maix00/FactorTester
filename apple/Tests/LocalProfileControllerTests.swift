import Foundation
import XCTest
@testable import FTClient

@MainActor
final class LocalProfileControllerTests: XCTestCase {
    func testHydratesLocalProfilesBeforeBundledCLIRefresh() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let profiles = root.appendingPathComponent("profiles")
        try FileManager.default.createDirectory(
            at: profiles,
            withIntermediateDirectories: true
        )
        defer { try? FileManager.default.removeItem(at: root) }
        let value: [String: Any] = [
            "profile_id": "maxa",
            "display_name": "MaxA",
        ]
        let data = try JSONSerialization.data(
            withJSONObject: value,
            options: []
        )
        try data.write(to: profiles.appendingPathComponent("maxa.json"))
        let suite = "LocalProfileControllerTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }

        let controller = LocalProfileController(
            defaults: defaults,
            profileDirectory: profiles
        )

        XCTAssertEqual(controller.profiles.map(\.id), ["maxa"])
        XCTAssertNotNil(defaults.data(forKey: "client.profile.list.cache.v1"))
        XCTAssertEqual(controller.loadState, .loaded)
    }

    func testLocalProfileStoreIgnoresRetiredResearchRecords() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let profiles = root.appendingPathComponent("profiles")
        try FileManager.default.createDirectory(
            at: profiles,
            withIntermediateDirectories: true
        )
        defer { try? FileManager.default.removeItem(at: root) }
        let current: [String: Any] = [
            "profile_id": "maxa",
            "display_name": "MaxA",
            "research_records": [["record_id": "retired-record"]],
        ]
        try JSONSerialization.data(withJSONObject: current).write(
            to: profiles.appendingPathComponent("maxa.json")
        )
        let stale: [[String: Any]] = [[
            "profile_id": "maxa",
            "display_name": "MaxA",
            "research_records": [["record_id": "stale-retired-record"]],
        ]]
        let suite = "LocalProfileControllerTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set(
            try JSONSerialization.data(withJSONObject: stale),
            forKey: "client.profile.list.cache.v1"
        )

        let controller = LocalProfileController(
            defaults: defaults,
            profileDirectory: profiles
        )

        XCTAssertEqual(controller.profiles.map(\.id), ["maxa"])
        XCTAssertEqual(controller.profiles.first?.displayName, "MaxA")
    }

    func testReloadsProfileWhenCLIReplacesLocalDescriptor() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let profiles = root.appendingPathComponent("profiles")
        try FileManager.default.createDirectory(
            at: profiles,
            withIntermediateDirectories: true
        )
        defer { try? FileManager.default.removeItem(at: root) }
        let profileURL = profiles.appendingPathComponent("maxa.json")
        try JSONSerialization.data(withJSONObject: [
            "profile_id": "maxa",
            "display_name": "MaxA",
        ]).write(to: profileURL)
        let suite = "LocalProfileControllerTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let controller = LocalProfileController(
            defaults: defaults,
            profileDirectory: profiles
        )

        try JSONSerialization.data(withJSONObject: [
            "profile_id": "maxa",
            "display_name": "MaxA updated",
        ]).write(to: profileURL, options: .atomic)

        for _ in 0..<30 where
            controller.profiles.first?.displayName != "MaxA updated" {
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTAssertEqual(
            controller.profiles.first?.displayName,
            "MaxA updated"
        )
    }

}
