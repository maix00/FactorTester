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
        XCTAssertEqual(controller.loadState, .loading)
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
}
