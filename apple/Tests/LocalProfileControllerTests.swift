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

    func testLocalProfileStoreSupersedesStaleCachedResearchRecords() throws {
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
            "research_records": [[
                "record_id": "stable-work-package",
                "graph_instance_ref": "work-package:stable-work-package",
            ]],
        ]
        try JSONSerialization.data(withJSONObject: current).write(
            to: profiles.appendingPathComponent("maxa.json")
        )
        let stale: [[String: Any]] = [[
            "profile_id": "maxa",
            "display_name": "MaxA",
            "research_records": [[
                "record_id": "old-physical-instance",
                "graph_instance_ref": "work-package:old-physical-instance",
            ]],
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

        XCTAssertEqual(
            controller.profiles.first?.researchRecords.map(\.id),
            ["stable-work-package"]
        )
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
            "display_name": "MaxA",
            "research_records": [[
                "record_id": "manual-research",
                "title": "动量因子辅助研究",
                "graph_instance_ref": "work-package:manual-research",
            ]],
        ]).write(to: profileURL, options: .atomic)

        for _ in 0..<30 where
            controller.profiles.first?.researchRecords.first?.title == nil {
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTAssertEqual(
            controller.profiles.first?.researchRecords.first?.title,
            "动量因子辅助研究"
        )
    }

}
