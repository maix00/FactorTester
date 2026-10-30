import Foundation

enum ClientCLIResolution {
    static func executable(
        bundle: Bundle = .main,
        defaults: UserDefaults = .standard,
        fileManager: FileManager = .default
    ) -> String {
        let bundled = firstExecutable([
            bundle.resourceURL?
                .appendingPathComponent("FactorTester/bin/traderesearch")
                .path,
            bundle.resourceURL?
                .appendingPathComponent("FactorTester/bin/factortester")
                .path,
        ]) { fileManager.isExecutableFile(atPath: $0) }
        return resolve(
            bundledPath: bundled,
            configuredPath: defaults.string(
                forKey: "client.release.cliPath"
            ),
            isExecutable: fileManager.isExecutableFile(atPath:)
        )
    }

    static func managerExecutable(
        bundle: Bundle = .main,
        defaults: UserDefaults = .standard,
        fileManager: FileManager = .default
    ) -> String {
        let bundled = firstExecutable([
            bundle.resourceURL?
                .appendingPathComponent("FactorTester/bin/traderesearch-manager")
                .path,
            bundle.resourceURL?
                .appendingPathComponent("FactorTester/bin/factortester-manager")
                .path,
        ]) { fileManager.isExecutableFile(atPath: $0) }
        return resolve(
            bundledPath: bundled,
            configuredPath: defaults.string(
                forKey: "client.release.managerCLIPath"
            ),
            isExecutable: fileManager.isExecutableFile(atPath:),
            fallback: "traderesearch-manager"
        )
    }

    static func resolve(
        bundledPath: String?,
        configuredPath: String?,
        isExecutable: (String) -> Bool,
        fallback: String = "traderesearch"
    ) -> String {
        if let bundledPath, isExecutable(bundledPath) {
            return bundledPath
        }
        if let configuredPath, !configuredPath.isEmpty {
            return configuredPath
        }
        return fallback
    }

    static func firstExecutable(
        _ candidates: [String?],
        isExecutable: (String) -> Bool
    ) -> String? {
        candidates.compactMap { $0 }.first(where: isExecutable)
    }
}
