import Foundation

enum LegacyAppNameMigration {
    static let currentName = "TradeResearch.app"
    static let legacyNames = ["FTClient.app", "FactorTester-Client.app"]
    static let bundleIdentifier = "com.gtht.client"

    @discardableResult
    static func run(
        applicationsDirectory: URL = URL(fileURLWithPath: "/Applications"),
        currentBundleURL: URL = Bundle.main.bundleURL,
        receiptRoot: URL? = nil
    ) throws -> Bool {
        guard currentBundleURL.lastPathComponent == currentName,
              currentBundleURL.deletingLastPathComponent()
                .resolvingSymlinksInPath().standardizedFileURL.path
                == applicationsDirectory.resolvingSymlinksInPath()
                    .standardizedFileURL.path else {
            return false
        }
        let legacy = legacyNames.map { applicationsDirectory.appendingPathComponent($0) }
            .filter { FileManager.default.fileExists(atPath: $0.path) }
        guard !legacy.isEmpty else { return false }
        // Validate every candidate before moving any of them.
        guard identifier(at: currentBundleURL) == bundleIdentifier,
              legacy.allSatisfy({ identifier(at: $0) == bundleIdentifier }) else {
            throw LegacyAppMigrationError.bundleIdentityMismatch
        }
        var retired: [(original: URL, hidden: URL)] = []
        do {
            for source in legacy {
                let hidden = applicationsDirectory.appendingPathComponent(
                    ".\(source.lastPathComponent).retired-\(UUID().uuidString)"
                )
                try FileManager.default.moveItem(at: source, to: hidden)
                retired.append((source, hidden))
            }
            let root = receiptRoot ?? FileManager.default.urls(
                for: .applicationSupportDirectory,
                in: .userDomainMask
            )[0].appendingPathComponent("TradeResearch/app-updates")
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
            let receipt: [String: Any] = [
                "schema_version": 2,
                "old_names": legacy.map { $0.lastPathComponent },
                "new_name": currentName,
                "bundle_identifier": bundleIdentifier,
                "status": "retired",
            ]
            let data = try JSONSerialization.data(withJSONObject: receipt, options: [.sortedKeys])
            try data.write(to: root.appendingPathComponent("app-name-migration.json"), options: .atomic)
        } catch {
            for item in retired.reversed() where !FileManager.default.fileExists(atPath: item.original.path) {
                try? FileManager.default.moveItem(at: item.hidden, to: item.original)
            }
            throw error
        }
        // The valid new application and the durable receipt now exist. Any
        // failed cleanup leaves a hidden copy rather than destroying data.
        for item in retired { try? FileManager.default.removeItem(at: item.hidden) }
        return true
    }

    private static func identifier(at app: URL) -> String? {
        let path = app.appendingPathComponent("Contents/Info.plist")
        guard let data = try? Data(contentsOf: path),
              let value = try? PropertyListSerialization.propertyList(
                from: data,
                format: nil
              ) as? [String: Any] else {
            return nil
        }
        return value["CFBundleIdentifier"] as? String
    }
}

enum LegacyAppMigrationError: LocalizedError {
    case bundleIdentityMismatch

    var errorDescription: String? {
        switch self {
        case .bundleIdentityMismatch:
            return L10n.text(
                "旧客户端身份校验失败，未删除任何应用。"
            )
        }
    }
}
