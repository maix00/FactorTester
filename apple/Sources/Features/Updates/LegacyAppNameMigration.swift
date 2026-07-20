import Foundation

enum LegacyAppNameMigration {
    static let currentName = "FTClient.app"
    static let legacyName = "FactorTester-Client.app"
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
        let legacy = applicationsDirectory.appendingPathComponent(legacyName)
        guard FileManager.default.fileExists(atPath: legacy.path) else {
            return false
        }
        guard identifier(at: currentBundleURL) == bundleIdentifier,
              identifier(at: legacy) == bundleIdentifier else {
            throw LegacyAppMigrationError.bundleIdentityMismatch
        }
        let hidden = applicationsDirectory.appendingPathComponent(
            ".\(legacyName).retired-\(UUID().uuidString)"
        )
        try FileManager.default.moveItem(at: legacy, to: hidden)
        do {
            let root = receiptRoot ?? FileManager.default.urls(
                for: .applicationSupportDirectory,
                in: .userDomainMask
            )[0].appendingPathComponent("FactorTester/app-updates")
            try FileManager.default.createDirectory(
                at: root,
                withIntermediateDirectories: true
            )
            let receipt: [String: Any] = [
                "schema_version": 1,
                "old_name": legacyName,
                "new_name": currentName,
                "bundle_identifier": bundleIdentifier,
                "status": "retired",
            ]
            let data = try JSONSerialization.data(
                withJSONObject: receipt,
                options: [.sortedKeys]
            )
            try data.write(
                to: root.appendingPathComponent("app-name-migration.json"),
                options: .atomic
            )
            try FileManager.default.removeItem(at: hidden)
            return true
        } catch {
            if !FileManager.default.fileExists(atPath: legacy.path) {
                try? FileManager.default.moveItem(at: hidden, to: legacy)
            }
            throw error
        }
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
